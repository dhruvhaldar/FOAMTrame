from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import vtk
from trame.widgets import client, html, vtk as vtk_widgets, vuetify

from backend.geometry.library import resolve_case_path
from backend.meshing.configuration import (
    MeshingConfiguration,
    build_block_mesh_dict,
    build_snappy_hex_mesh_dict,
    list_meshing_surfaces,
    load_surface_dataset,
    suggest_meshing_configuration,
    validate_meshing_configuration,
    write_meshing_dictionaries,
)
from backend.meshing.inspection import inspect_case_mesh, load_latest_quality_report
from backend.meshing.progress import meshing_progress
from backend.meshing.reader import read_mesh_patches

logger = logging.getLogger("FOAMTrame")

renderer = vtk.vtkRenderer()
renderer.SetBackground(0.72, 0.94, 1.0)
renderer.SetBackground2(0.92, 0.85, 0.91)
renderer.GradientBackgroundOn()
render_window = vtk.vtkRenderWindow()
render_window.SetOffScreenRendering(1)
render_window.SetMultiSamples(0)
render_window.AddRenderer(renderer)
interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(render_window)
interactor_style = vtk.vtkInteractorStyleTrackballCamera()
interactor.SetInteractorStyle(interactor_style)
interactor.GetInteractorStyle().SetCurrentRenderer(renderer)
interactor.Initialize()
mesh_actor = vtk.vtkAssembly()
patch_actors: dict[str, vtk.vtkActor] = {}
mesh_actor.SetVisibility(False)
renderer.AddActor(mesh_actor)
surface_preview_mapper = vtk.vtkPolyDataMapper()
surface_preview_actor = vtk.vtkActor()
surface_preview_actor.SetMapper(surface_preview_mapper)
surface_preview_actor.GetProperty().SetColor(0.14, 0.49, 0.61)
surface_preview_actor.SetVisibility(False)
renderer.AddActor(surface_preview_actor)
domain_source = vtk.vtkCubeSource()
domain_mapper = vtk.vtkPolyDataMapper()
domain_mapper.SetInputConnection(domain_source.GetOutputPort())
domain_actor = vtk.vtkActor()
domain_actor.SetMapper(domain_mapper)
domain_actor.GetProperty().SetRepresentationToWireframe()
domain_actor.GetProperty().SetColor(0.08, 0.36, 0.50)
domain_actor.GetProperty().SetLineWidth(2)
domain_actor.SetVisibility(False)
renderer.AddActor(domain_actor)


def setup_meshing_tab(server):
    state, ctrl = server.state, server.controller
    defaults = {
        "mesh_available": False,
        "mesh_status": "Select an active case",
        "mesh_points": None,
        "mesh_faces": None,
        "mesh_internal_faces": None,
        "mesh_cells": None,
        "mesh_patches": [],
        "mesh_missing_files": [],
        "mesh_render_error": "",
        "mesh_quality_available": False,
        "mesh_quality_passed": False,
        "mesh_quality_status": "Run checkMesh to evaluate mesh quality",
        "mesh_quality_failed_checks": 0,
        "mesh_quality_max_non_orthogonality": None,
        "mesh_quality_average_non_orthogonality": None,
        "mesh_quality_max_skewness": None,
        "mesh_quality_max_aspect_ratio": None,
        "mesh_quality_source": "",
        "mesh_report_dialog": False,
        "mesh_report_sections": [],
        "mesh_report_warnings": [],
        "mesh_report_log": "",
        "mesh_visible_patches": [],
        "mesh_patch_transparency": {},
        "mesh_check_requested": False,
        "mesh_generation_status": "Choose a case surface to configure meshing.",
        "mesh_generation_error": False,
        "mesh_preview_error": False,
        "mesh_surface_options": [],
        "mesh_surface_selection": "",
        "mesh_domain_padding": 20,
        "mesh_base_fineness": 5,
        "mesh_refinement_min": 2,
        "mesh_refinement_max": 3,
        "mesh_surface_layers": 3,
        "mesh_domain_bounds": [],
        "mesh_base_cells": [],
        "mesh_review_dialog": False,
        "mesh_review_block_dict": "",
        "mesh_review_snappy_dict": "",
        "mesh_review_existing": [],
        "mesh_review_estimated_cells": 0,
        "mesh_review_mode": "",
        "mesh_generation_ready": False,
        "mesh_job_busy": False,
        "mesh_job_failed": False,
        "mesh_job_phase": "",
        "mesh_job_message": "",
    }
    for key, value in defaults.items():
        state.setdefault(key, value)

    event_loop = [None]
    view_ready = [False]
    reviewed_config: list[MeshingConfiguration | None] = [None]
    reviewed_case: list[Path | None] = [None]
    tracked_jobs: dict[str, int] = {}

    @ctrl.add("on_server_ready")
    def capture_meshing_event_loop(**_):
        event_loop[0] = asyncio.get_running_loop()

    @ctrl.add("on_client_connected")
    def enable_meshing_view(**_):
        view_ready[0] = True
        if mesh_actor.GetVisibility() and ctrl.mesh_view_update.exists():
            ctrl.mesh_view_update()

    def publish(*keys: str) -> None:
        state.dirty(*keys)
        state.flush()
        loop = event_loop[0]
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(server.force_state_push, *keys)

    def current_case_path() -> Path | None:
        case_root = str(getattr(state, "case_root", "") or "")
        active_case = str(getattr(state, "active_case", "") or "")
        if not case_root or not active_case:
            return None
        try:
            path = resolve_case_path(case_root, active_case)
        except ValueError:
            return None
        return path if path.is_dir() else None

    def refresh_surface_options() -> None:
        case_path = current_case_path()
        try:
            options = list_meshing_surfaces(case_path)
        except ValueError:
            options = []
        state.mesh_surface_options = options
        values = {option["value"] for option in options}
        if state.mesh_surface_selection not in values:
            state.mesh_surface_selection = options[0]["value"] if options else ""
        state.mesh_generation_ready = bool(options)
        state.mesh_generation_status = (
            "Choose the domain and mesh controls, then review the dictionaries."
            if options
            else "Add a closed STL or OBJ surface to constant/geometry or constant/triSurface first."
        )
        state.mesh_generation_error = False
        publish(
            "mesh_surface_options",
            "mesh_surface_selection",
            "mesh_generation_ready",
            "mesh_generation_status",
            "mesh_generation_error",
        )

    def proposed_configuration() -> MeshingConfiguration:
        case_path = current_case_path()
        if case_path is None:
            raise ValueError("Select an active case before configuring a mesh.")
        return suggest_meshing_configuration(
            case_path,
            str(state.mesh_surface_selection or ""),
            padding_percent=float(state.mesh_domain_padding),
            fineness=int(state.mesh_base_fineness),
            refinement_min=int(state.mesh_refinement_min),
            refinement_max=int(state.mesh_refinement_max),
            surface_layers=int(state.mesh_surface_layers),
        )

    def render_surface_preview(case_path: Path, config: MeshingConfiguration) -> None:
        dataset = load_surface_dataset(case_path, config.surface_file)
        surface_preview_mapper.SetInputData(dataset)
        surface_preview_actor.SetVisibility(True)
        domain_source.SetBounds(*config.bounds)
        domain_source.Update()
        domain_actor.SetVisibility(True)
        mesh_actor.SetVisibility(False)
        renderer.ResetCamera()
        renderer.ResetCameraClippingRange()
        if view_ready[0] and ctrl.mesh_view_update.exists():
            render_window.Render()
            ctrl.mesh_view_update()

    def preview_mesh_configuration():
        if state.mesh_job_busy:
            return
        try:
            config = proposed_configuration()
            case_path = current_case_path()
            assert case_path is not None
            state.mesh_domain_bounds = list(config.bounds)
            state.mesh_base_cells = list(config.base_cells)
            state.mesh_review_estimated_cells = (
                config.base_cells[0] * config.base_cells[1] * config.base_cells[2]
            )
            state.mesh_generation_error = False
            state.mesh_preview_error = False
            state.mesh_generation_status = (
                "Domain preview ready. Review the generated dictionaries before saving."
            )
            if not state.mesh_available:
                render_surface_preview(case_path, config)
        except (ValueError, OSError, OverflowError) as exc:
            state.mesh_generation_error = True
            state.mesh_preview_error = True
            state.mesh_generation_status = str(exc)
            surface_preview_actor.SetVisibility(False)
            domain_actor.SetVisibility(False)
        publish(
            "mesh_domain_bounds",
            "mesh_base_cells",
            "mesh_review_estimated_cells",
            "mesh_generation_error",
            "mesh_preview_error",
            "mesh_generation_status",
        )

    def review_mesh_generation(mode: str = "save"):
        try:
            if state.mesh_job_busy:
                raise ValueError("Wait for the current meshing job to finish.")
            if mode not in {"save", "generate"}:
                raise ValueError("Unknown meshing action.")
            case_path = current_case_path()
            if case_path is None:
                raise ValueError("Select an active case before configuring a mesh.")
            config = validate_meshing_configuration(proposed_configuration())
            if mode == "generate":
                from tabs.setup_tab import get_docker_client

                if get_docker_client() is None:
                    raise ValueError(
                        "Docker is unavailable. Save the dictionaries and generate later."
                    )
                if (case_path / "constant" / "polyMesh").is_dir():
                    raise ValueError(
                        "A generated mesh already exists. Review case cleanup before regenerating."
                    )
            reviewed_config[0] = config
            reviewed_case[0] = case_path
            state.mesh_review_block_dict = build_block_mesh_dict(config)
            state.mesh_review_snappy_dict = build_snappy_hex_mesh_dict(config)
            state.mesh_review_existing = [
                name
                for name in ("blockMeshDict", "snappyHexMeshDict")
                if (case_path / "system" / name).exists()
            ]
            state.mesh_review_mode = mode
            state.mesh_review_dialog = True
            state.mesh_generation_error = False
        except (ValueError, OSError, OverflowError) as exc:
            state.mesh_generation_error = True
            state.mesh_generation_status = str(exc)
            reviewed_config[0] = None
            reviewed_case[0] = None
        publish(
            "mesh_review_block_dict",
            "mesh_review_snappy_dict",
            "mesh_review_existing",
            "mesh_review_mode",
            "mesh_review_dialog",
            "mesh_generation_error",
            "mesh_generation_status",
        )

    def confirm_mesh_generation():
        config, case_path = reviewed_config[0], reviewed_case[0]
        mode = str(state.mesh_review_mode or "")
        state.mesh_review_dialog = False
        reviewed_config[0] = None
        reviewed_case[0] = None
        try:
            if config is None or case_path is None or case_path != current_case_path():
                raise ValueError(
                    "The active case changed. Review the configuration again."
                )
            if any(
                item.get("case_name") == case_path.name
                for item in list(state.simulation_queue or [])
            ):
                raise ValueError(
                    "A job for this case is queued or running. Save after it finishes."
                )
            if mode == "generate" and (case_path / "constant" / "polyMesh").is_dir():
                raise ValueError(
                    "A generated mesh now exists. Review case cleanup first."
                )
            result = write_meshing_dictionaries(case_path, config)
            if result.staged_surface is not None:
                state.mesh_surface_selection = "geometry/" + result.staged_surface.name
                refresh_surface_options()
            state.mesh_generation_error = False
            state.mesh_generation_status = (
                "Saved blockMeshDict and snappyHexMeshDict"
                + (
                    f"; originals backed up in {result.backup_directory.relative_to(case_path)}"
                    if result.backup_directory
                    else ""
                )
                + (
                    f"; imported surface copied to constant/geometry/{result.staged_surface.name}"
                    if result.staged_surface
                    else ""
                )
                + "."
            )
            ctrl.scan_case_capabilities()
            if mode == "generate":
                job_id = ctrl.request_case_actions(
                    ("blockMesh", "snappyHexMeshOverwrite"), "Generate mesh"
                )
                if job_id is None:
                    raise ValueError(
                        "Meshing could not be queued. Open Run/Log for details."
                    )
                tracked_jobs[str(case_path)] = job_id
                sync_mesh_job_progress()
                state.mesh_generation_status += " Meshing job submitted to Run/Log."
        except (ValueError, OSError) as exc:
            state.mesh_generation_error = True
            state.mesh_generation_status = str(exc)
        publish(
            "mesh_review_dialog",
            "mesh_surface_selection",
            "mesh_generation_error",
            "mesh_generation_status",
        )

    def update_mesh_view(case_path: Path | None, reset_camera: bool = True) -> None:
        mesh_actor.SetVisibility(False)
        surface_preview_actor.SetVisibility(False)
        domain_actor.SetVisibility(False)
        state.mesh_render_error = ""
        if case_path is None or not state.mesh_available:
            publish("mesh_render_error")
            if view_ready[0] and ctrl.mesh_view_update.exists():
                ctrl.mesh_view_update()
            return
        try:
            for actor in patch_actors.values():
                mesh_actor.RemovePart(actor)
            patch_actors.clear()
            for name, dataset in read_mesh_patches(case_path).items():
                mapper = vtk.vtkPolyDataMapper()
                mapper.ScalarVisibilityOff()
                mapper.SetInputData(dataset)
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor(0.10, 0.61, 0.70)
                actor.GetProperty().SetEdgeColor(0.08, 0.22, 0.28)
                actor.GetProperty().EdgeVisibilityOn()
                actor.GetProperty().SetLineWidth(0.7)
                actor.SetVisibility(name in state.mesh_visible_patches)
                actor.GetProperty().SetOpacity(
                    1 - state.mesh_patch_transparency.get(name, 0) / 100
                )
                patch_actors[name] = actor
                mesh_actor.AddPart(actor)
            mesh_actor.SetVisibility(True)
            if reset_camera:
                renderer.ResetCamera()
            renderer.ResetCameraClippingRange()
        except Exception as exc:
            logger.warning("Could not render OpenFOAM mesh: %s", exc)
            state.mesh_render_error = str(exc)
        publish("mesh_render_error")
        if view_ready[0] and ctrl.mesh_view_update.exists():
            render_window.Render()
            ctrl.mesh_view_update()

    def refresh_mesh_inspection():
        if state.mesh_job_busy:
            return
        case_path = current_case_path()
        refresh_surface_options()
        mesh_inspection = inspect_case_mesh(case_path)
        inspection = mesh_inspection.to_state()
        patch_names = [patch.name for patch in mesh_inspection.patches]
        quality = load_latest_quality_report(case_path).to_state()
        state.mesh_available = inspection["available"]
        state.mesh_status = inspection["status"]
        state.mesh_points = inspection["points"]
        state.mesh_faces = inspection["faces"]
        state.mesh_internal_faces = inspection["internal_faces"]
        state.mesh_cells = quality["cells"] if quality["available"] else None
        previous_names = {patch["name"] for patch in state.mesh_patches}
        selected = set(state.mesh_visible_patches)
        state.mesh_patches = inspection["patches"]
        state.mesh_visible_patches = [
            name
            for name in patch_names
            if name in selected or name not in previous_names
        ]
        state.mesh_patch_transparency = {
            name: state.mesh_patch_transparency.get(name, 0) for name in patch_names
        }
        state.mesh_missing_files = inspection["missing_files"]
        state.mesh_quality_available = quality["available"]
        state.mesh_quality_passed = quality["passed"]
        state.mesh_quality_status = quality["status"]
        state.mesh_quality_failed_checks = quality["failed_checks"]
        state.mesh_quality_max_non_orthogonality = quality["max_non_orthogonality"]
        state.mesh_quality_average_non_orthogonality = quality[
            "average_non_orthogonality"
        ]
        state.mesh_quality_max_skewness = quality["max_skewness"]
        state.mesh_quality_max_aspect_ratio = quality["max_aspect_ratio"]
        state.mesh_quality_source = quality["source"]
        state.mesh_report_sections = quality["sections"]
        state.mesh_report_warnings = quality["warnings"]
        state.mesh_report_log = quality["log_text"]
        state.mesh_check_requested = False
        if quality["available"]:
            state.mesh_points = quality["points"] or state.mesh_points
            state.mesh_faces = quality["faces"] or state.mesh_faces
        publish(*defaults.keys())

        def update_and_preview() -> None:
            if case_path != current_case_path() or state.mesh_job_busy:
                return
            update_mesh_view(case_path)
            if (
                case_path is not None
                and not state.mesh_available
                and state.mesh_surface_selection
            ):
                preview_mesh_configuration()

        loop = event_loop[0]
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(update_and_preview)
        else:
            update_and_preview()

    def run_mesh_check():
        state.mesh_check_requested = True
        state.mesh_quality_status = "checkMesh queued in Run/Log"
        publish("mesh_check_requested", "mesh_quality_status")
        ctrl.request_case_action("checkMesh")

    def reset_mesh_camera():
        renderer.ResetCamera()
        renderer.ResetCameraClippingRange()
        if ctrl.mesh_view_update.exists():
            ctrl.mesh_view_update()

    ctrl.refresh_mesh_inspection = refresh_mesh_inspection
    ctrl.run_mesh_check = run_mesh_check
    ctrl.reset_mesh_camera = reset_mesh_camera
    ctrl.preview_mesh_configuration = preview_mesh_configuration
    ctrl.review_mesh_generation = review_mesh_generation
    ctrl.confirm_mesh_generation = confirm_mesh_generation

    @state.change("mesh_visible_patches", "mesh_patch_transparency")
    def on_patch_visibility_change(**_):
        if not state.mesh_job_busy and state.mesh_available:
            for name, actor in patch_actors.items():
                actor.SetVisibility(name in state.mesh_visible_patches)
                try:
                    transparency = float(state.mesh_patch_transparency.get(name, 0))
                except (ValueError, TypeError):
                    transparency = 0
                actor.GetProperty().SetOpacity(1 - max(0, min(100, transparency)) / 100)
            if view_ready[0] and ctrl.mesh_view_update.exists():
                ctrl.mesh_view_update()

    def set_mesh_patch_transparency(name: str, value: float) -> None:
        if name not in patch_actors:
            return
        try:
            transparency = max(0, min(100, float(value)))
        except (ValueError, TypeError):
            return
        state.mesh_patch_transparency = {
            **state.mesh_patch_transparency,
            name: transparency,
        }
        publish("mesh_patch_transparency")
        on_patch_visibility_change()

    ctrl.set_mesh_patch_transparency = set_mesh_patch_transparency

    def sync_mesh_job_progress(refresh_on_finish: bool = True):
        case_path = current_case_path()
        progress = meshing_progress(
            case_path,
            list(state.simulation_queue or []),
            list(state.run_history or []),
            tracked_jobs.get(str(case_path)),
        )
        if progress["job_id"] is not None and case_path is not None:
            tracked_jobs[str(case_path)] = progress["job_id"]
        was_busy = state.mesh_job_busy
        state.mesh_job_busy = progress["busy"]
        state.mesh_job_failed = progress["failed"]
        state.mesh_job_phase = progress["phase"]
        state.mesh_job_message = progress["message"]
        publish(
            "mesh_job_busy", "mesh_job_failed", "mesh_job_phase", "mesh_job_message"
        )
        if was_busy and not progress["busy"] and refresh_on_finish:
            refresh_mesh_inspection()

    @state.change("simulation_queue", "run_history")
    def on_mesh_job_change(**_):
        loop = event_loop[0]
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(sync_mesh_job_progress)
        else:
            sync_mesh_job_progress()

    def dismiss_mesh_job_status():
        tracked_jobs.pop(str(current_case_path()), None)
        sync_mesh_job_progress()
        refresh_mesh_inspection()

    ctrl.dismiss_mesh_job_status = dismiss_mesh_job_status

    @state.change("active_case", "case_root")
    def on_active_case_change_mesh(**_):
        state.mesh_patches = []
        state.mesh_patch_transparency = {}
        state.mesh_report_dialog = False
        state.mesh_check_requested = False
        state.mesh_review_dialog = False
        reviewed_config[0] = None
        reviewed_case[0] = None
        sync_mesh_job_progress(refresh_on_finish=False)
        refresh_mesh_inspection()

    refresh_mesh_inspection()


def build_meshing_drawer():
    from trame.app import get_server

    server = get_server()
    assert server is not None
    ctrl = server.controller
    with html.Div(
        v_show="active_tab === 2",
        classes="pa-4 meshing-drawer",
        role="region",
        aria_label="Mesh inspection controls",
    ):
        html.H2("Mesh workspace", classes="text-subtitle-1 font-weight-bold mb-1")
        html.P(
            "Create, inspect, and validate the active case mesh.",
            classes="text-caption text--secondary mb-3",
        )
        with vuetify.VCard(classes="glass-card pa-3 mb-3 mesh-generator-card"):
            html.H3("Generate mesh", classes="text-subtitle-1 font-weight-bold mb-1")
            html.P(
                "Choose a closed STL or OBJ case surface. The padded domain "
                "and base cells are estimated from its bounds.",
                classes="text-caption text--secondary mb-2",
            )
            vuetify.VSelect(
                v_model=("mesh_surface_selection",),
                items=("mesh_surface_options",),
                label="Case surface",
                dense=True,
                outlined=True,
                hide_details=True,
                disabled=("!mesh_generation_ready || mesh_job_busy",),
                classes="mb-3",
                change=ctrl.preview_mesh_configuration,
            )
            html.Div(
                "Domain padding: {{ mesh_domain_padding }}%",
                classes="text-caption font-weight-medium",
            )
            vuetify.VSlider(
                v_model=("mesh_domain_padding",),
                min=5,
                max=100,
                step=5,
                thumb_label=True,
                append_icon="mdi-percent-outline",
                disabled=("mesh_job_busy",),
                hide_details=True,
                change=ctrl.preview_mesh_configuration,
            )
            html.Div(
                "Base mesh fineness: {{ mesh_base_fineness }}/10",
                classes="text-caption font-weight-medium mt-2",
            )
            vuetify.VSlider(
                v_model=("mesh_base_fineness",),
                disabled=("mesh_job_busy",),
                min=1,
                max=10,
                step=1,
                thumb_label=True,
                hide_details=True,
                change=ctrl.preview_mesh_configuration,
            )
            html.Div(
                "Surface refinement: {{ mesh_refinement_min }} / {{ mesh_refinement_max }}",
                classes="text-caption font-weight-medium mt-2",
            )
            with html.Div(classes="mesh-control-pair"):
                vuetify.VSlider(
                    v_model=("mesh_refinement_min",),
                    disabled=("mesh_job_busy",),
                    min=0,
                    max=8,
                    step=1,
                    thumb_label=True,
                    hide_details=True,
                    change=ctrl.preview_mesh_configuration,
                    aria_label="Minimum surface refinement level",
                )
                vuetify.VSlider(
                    v_model=("mesh_refinement_max",),
                    disabled=("mesh_job_busy",),
                    min=0,
                    max=8,
                    step=1,
                    thumb_label=True,
                    hide_details=True,
                    change=ctrl.preview_mesh_configuration,
                    aria_label="Maximum surface refinement level",
                )
            html.Div(
                "Boundary layers: {{ mesh_surface_layers }}",
                classes="text-caption font-weight-medium mt-2",
            )
            vuetify.VSlider(
                v_model=("mesh_surface_layers",),
                disabled=("mesh_job_busy",),
                min=0,
                max=10,
                step=1,
                thumb_label=True,
                hide_details=True,
                change=ctrl.preview_mesh_configuration,
            )
            html.P(
                "Domain: {{ mesh_domain_bounds.length === 6 ? mesh_domain_bounds.map(v => Number(v).toPrecision(3)).join(', ') : '—' }}",
                classes="text-caption mesh-control-summary mb-1",
            )
            html.P(
                "Base cells: {{ mesh_base_cells.length === 3 ? mesh_base_cells.join(' × ') : '—' }}",
                classes="text-caption mesh-control-summary mb-2",
            )
            html.P(
                "{{ mesh_job_busy ? mesh_job_phase + '. ' + mesh_job_message : mesh_generation_status }}",
                classes="text-caption mb-2",
                style=("mesh_generation_error ? 'color:#a32d2d' : 'color:#435769'",),
                role="status",
                aria_live="polite",
            )
            with html.Div(classes="mesh-generator-actions"):
                vuetify.VBtn(
                    "Review & save",
                    click=(ctrl.review_mesh_generation, "['save']"),
                    disabled=("!mesh_generation_ready || mesh_job_busy",),
                    outlined=True,
                    color="cyan darken-3",
                    small=True,
                )
                vuetify.VBtn(
                    "Generate mesh",
                    click=(ctrl.review_mesh_generation, "['generate']"),
                    disabled=(
                        "!mesh_generation_ready || docker_checking || mesh_job_busy",
                    ),
                    color="cyan darken-3",
                    classes="mesh-generate-btn",
                    small=True,
                )
        with vuetify.VCard(classes="glass-card pa-3 mb-3"):
            with html.Div(classes="d-flex align-center mb-2"):
                vuetify.VIcon(
                    "{{ mesh_available ? 'mdi-check-decagram' : 'mdi-cube-off-outline' }}",
                    color=("mesh_available ? 'teal darken-2' : 'blue-grey'",),
                    classes="mr-2",
                )
                html.Strong(
                    "{{ mesh_job_busy ? mesh_job_phase : mesh_status }}",
                    classes="text-body-2",
                )
            html.Div(
                "{{ active_case || 'No active case' }}",
                classes="text-caption text--secondary mb-2",
            )
            with html.Div(v_if="mesh_available", classes="mesh-stat-grid"):
                html.Div("Points", classes="mesh-stat-label")
                html.Strong(
                    "{{ mesh_points == null ? '—' : mesh_points.toLocaleString() }}"
                )
                html.Div("Faces", classes="mesh-stat-label")
                html.Strong(
                    "{{ mesh_faces == null ? '—' : mesh_faces.toLocaleString() }}"
                )
                html.Div("Cells", classes="mesh-stat-label")
                html.Strong(
                    "{{ mesh_cells == null ? 'Run checkMesh' : mesh_cells.toLocaleString() }}"
                )
                html.Div("Patches", classes="mesh-stat-label")
                html.Strong("{{ mesh_patches.length }}")

        with vuetify.VCard(classes="glass-card pa-3 mb-3"):
            html.Div("Mesh quality", classes="font-weight-bold mb-1")
            vuetify.VChip(
                "{{ mesh_quality_passed ? 'Passed' : (mesh_quality_available ? 'Needs attention' : 'Not checked') }}",
                small=True,
                outlined=True,
                color=(
                    "mesh_quality_passed ? 'success' : (mesh_quality_available ? 'warning' : 'blue-grey')",
                ),
                classes="mb-2",
            )
            html.P(
                "{{ mesh_quality_status }}",
                classes="text-caption text--secondary mb-2",
                role="status",
                aria_live="polite",
            )
            html.Div(
                "Latest report: {{ mesh_quality_source }}",
                v_if="mesh_quality_source",
                classes="text-caption text--secondary mb-2",
            )
            vuetify.VBtn(
                "Run checkMesh",
                click=ctrl.run_mesh_check,
                block=True,
                color="cyan darken-3",
                dark=True,
                loading=("mesh_check_requested", False),
                disabled=(
                    "!mesh_available || capability_scanning || !case_action_map.checkMesh.available",
                ),
                title=("case_action_map.checkMesh.reason",),
            )
            vuetify.VBtn(
                "Detailed report",
                click="mesh_report_dialog = true",
                disabled=("!mesh_quality_available || mesh_job_busy",),
                block=True,
                outlined=True,
                color="cyan darken-3",
                classes="mt-2",
            )
        with vuetify.VDialog(
            v_model=("mesh_report_dialog", False),
            max_width="900",
            raw_attrs=['aria-labelledby="mesh-report-title"'],
            scrollable=True,
        ):
            with vuetify.VCard(classes="glass-card capability-dialog"):
                with html.Div(
                    classes="capability-dialog__header pa-4 d-flex align-center"
                ):
                    with html.Div():
                        html.H2(
                            "checkMesh report",
                            id="mesh-report-title",
                            classes="text-h6",
                        )
                        html.Div("{{ mesh_quality_status }}", role="status")
                        html.Div(
                            "{{ mesh_quality_source }}",
                            classes="text-caption",
                            style="overflow-wrap:anywhere",
                        )
                    vuetify.VSpacer()
                    with vuetify.VBtn(
                        icon=True,
                        click="mesh_report_dialog = false",
                        raw_attrs=['aria-label="Close checkMesh report"'],
                    ):
                        vuetify.VIcon("mdi-close")
                with vuetify.VCardText(
                    classes="pa-4", style="max-height:70vh;overflow-y:auto"
                ):
                    html.P(
                        "Values and verdicts are read from the latest checkMesh log. Reported means no explicit pass/fail verdict was supplied."
                    )
                    with vuetify.VAlert(
                        v_if="mesh_report_warnings.length",
                        outlined=True,
                        type="warning",
                        color="orange darken-4",
                    ):
                        html.Strong("Warnings and failures")
                        html.Div(
                            "{{ warning }}",
                            v_for="(warning, index) in mesh_report_warnings",
                            key=("index",),
                            style="overflow-wrap:anywhere",
                        )
                    with html.Section(
                        v_for="(section, index) in mesh_report_sections",
                        key=("index",),
                        classes="mb-4",
                    ):
                        html.H3(
                            "{{ section.title }}",
                            classes="text-subtitle-1 font-weight-bold mb-2",
                        )
                        with html.Div(
                            v_for="(row, rowIndex) in section.rows",
                            key=("rowIndex",),
                            classes="d-flex align-start py-2",
                            style="gap:12px;border-bottom:1px solid #cce0e5",
                        ):
                            html.Span(
                                "{{ row.text }}",
                                style="flex:1;min-width:0;overflow-wrap:anywhere",
                            )
                            vuetify.VChip(
                                "{{ row.status }}",
                                small=True,
                                outlined=True,
                                style="flex-shrink:0;width:82px;justify-content:center",
                                color=(
                                    "row.status === 'Failed' ? 'error' : row.status === 'Warning' ? 'orange darken-3' : row.status === 'Passed' ? 'teal darken-3' : 'blue-grey'",
                                ),
                            )
                    with html.Details():
                        html.Summary("Supporting log text", classes="font-weight-bold")
                        html.Pre(
                            "{{ mesh_report_log }}",
                            style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px",
                            classes="mt-2",
                        )
        vuetify.VBtn(
            "Refresh mesh",
            disabled=("mesh_job_busy",),
            click=ctrl.refresh_mesh_inspection,
            block=True,
            outlined=True,
            color="cyan darken-3",
            classes="mb-2",
        )
        vuetify.VBtn(
            "Reset camera",
            click=ctrl.reset_mesh_camera,
            block=True,
            outlined=True,
            disabled=(
                "mesh_job_busy || (!mesh_available && !mesh_generation_ready) || !!mesh_render_error",
            ),
        )
        with vuetify.VDialog(v_model=("mesh_review_dialog", False), max_width="900"):
            with vuetify.VCard(classes="glass-card mesh-review-dialog pa-4"):
                html.H2("Review meshing dictionaries", classes="text-h6 mb-2")
                html.P(
                    "{{ mesh_review_mode === 'generate' ? 'Save and queue blockMesh → snappyHexMesh.' : 'Save dictionaries for a later meshing run.' }}",
                    classes="text-body-2 mb-2",
                )
                html.P(
                    "{{ mesh_review_estimated_cells.toLocaleString() }} base cells before refinement. Surface refinement and layers can increase this substantially.",
                    classes="text-caption mb-2",
                )
                html.P(
                    "Existing dictionaries will be backed up: {{ mesh_review_existing.join(', ') }}",
                    v_if="mesh_review_existing.length",
                    classes="text-caption font-weight-bold mb-2",
                )
                html.P(
                    "The padded corner used as insidePoint must lie in "
                    "the intended fluid region. "
                    "Review patch conditions after meshing.",
                    classes="text-caption mb-3",
                )
                html.H3("system/blockMeshDict", classes="text-subtitle-2")
                html.Pre(
                    "{{ mesh_review_block_dict }}", classes="mesh-dictionary-preview"
                )
                html.H3("system/snappyHexMeshDict", classes="text-subtitle-2 mt-3")
                html.Pre(
                    "{{ mesh_review_snappy_dict }}", classes="mesh-dictionary-preview"
                )
                with html.Div(
                    classes="d-flex justify-end flex-wrap mesh-review-actions mt-3"
                ):
                    vuetify.VBtn(
                        "Cancel", text=True, click="mesh_review_dialog = false"
                    )
                    vuetify.VBtn(
                        "{{ mesh_review_mode === 'generate' ? 'Save & queue' : 'Save dictionaries' }}",
                        color="cyan darken-3",
                        dark=True,
                        click=ctrl.confirm_mesh_generation,
                    )


def build_meshing_content():
    from trame.app import get_server

    server = get_server()
    assert server is not None
    ctrl = server.controller
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-0 meshing-viewer",
        v_if="active_tab === 2",
        aria_busy=("mesh_job_busy ? 'true' : 'false'",),
    ):
        with html.Div(
            v_if="mesh_job_busy || mesh_job_failed",
            classes="meshing-job-screen",
        ):
            with html.Div(
                classes="meshing-job-card", role="status", aria_live="polite"
            ):
                vuetify.VProgressCircular(
                    v_if="mesh_job_busy",
                    indeterminate=True,
                    size=60,
                    width=5,
                    color="cyan darken-3",
                    aria_label="Meshing in progress",
                )
                vuetify.VIcon(
                    "mdi-alert-circle-outline",
                    v_else=True,
                    size=60,
                    color="warning",
                )
                html.H2("{{ mesh_job_phase }}", classes="text-h6 mt-4 mb-2")
                html.P("{{ mesh_job_message }}", classes="text-body-2 mb-4")
                vuetify.VBtn(
                    "Open Run/Log",
                    click="active_tab = 3",
                    outlined=True,
                    color="cyan darken-3",
                )
                vuetify.VBtn(
                    "Inspect available data",
                    v_if="mesh_job_failed",
                    click=ctrl.dismiss_mesh_job_status,
                    text=True,
                    color="cyan darken-3",
                    classes="mt-2",
                )
        with html.Div(
            v_if="!mesh_job_busy && !mesh_job_failed && ((!mesh_available && (!mesh_generation_ready || mesh_preview_error)) || mesh_render_error)",
            classes="meshing-empty-state",
            role="status",
        ):
            vuetify.VIcon(
                "{{ mesh_available ? 'mdi-alert-circle-outline' : 'mdi-grid-off' }}",
                size=58,
                color="blue-grey lighten-1",
            )
            html.H2(
                "{{ mesh_available ? 'Mesh preview unavailable' : 'No complete mesh detected' }}",
                classes="text-h6 mt-3 mb-1",
            )
            html.P(
                "{{ mesh_render_error || (mesh_preview_error ? mesh_generation_status : mesh_status) }}",
                classes="text-body-2 mb-0",
            )
        view = vtk_widgets.VtkRemoteView(
            render_window,
            interactive_ratio=1,
            classes="fill-height w-100",
        )
        ctrl.mesh_view_update = view.update
        ctrl.mesh_view_reset_camera = view.reset_camera
        client.ClientTriggers(ref="mesh_view_mount", mounted=ctrl.mesh_view_update)
        with html.Div(
            v_if="!mesh_job_busy && !mesh_job_failed && !mesh_available && mesh_generation_ready && !mesh_preview_error",
            classes="mesh-preview-hint",
        ):
            html.Strong("Domain preview")
            html.Div("Surface and padded base-mesh domain")
        with html.Div(
            v_if="!mesh_job_busy && !mesh_job_failed && mesh_available",
            classes="mesh-inspector-overlay",
            role="region",
            aria_label="Mesh patches and quality",
        ):
            html.H3("Boundary patches", classes="text-subtitle-2 font-weight-bold mb-2")
            with html.Div(classes="d-flex mb-2"):
                vuetify.VBtn(
                    "Show all",
                    small=True,
                    text=True,
                    click="mesh_visible_patches = mesh_patches.map(p => p.name)",
                )
                vuetify.VBtn(
                    "Hide all", small=True, text=True, click="mesh_visible_patches = []"
                )
            with html.Div(classes="mesh-patch-list"):
                with html.Div(
                    v_for="patch in mesh_patches",
                    key=("patch.name",),
                    classes="mesh-patch-row",
                ):
                    vuetify.VCheckbox(
                        v_model=("mesh_visible_patches", []),
                        value=("patch.name",),
                        label=("patch.name",),
                        dense=True,
                        hide_details=True,
                        classes="mt-0 pt-0",
                        color="cyan darken-3",
                    )
                    html.Span(
                        "{{ patch.patch_type }} · {{ patch.face_count == null ? '—' : patch.face_count.toLocaleString() + ' faces' }}",
                        classes="text-caption text--secondary",
                    )
                    vuetify.VSlider(
                        v_model=("mesh_patch_transparency[patch.name]",),
                        change=(
                            ctrl.set_mesh_patch_transparency,
                            "[patch.name, $event]",
                        ),
                        label=(
                            "'Transparency ' + (mesh_patch_transparency[patch.name] || 0) + '%'",
                        ),
                        min=0,
                        max=100,
                        step=5,
                        dense=True,
                        hide_details=True,
                        disabled=("!mesh_visible_patches.includes(patch.name)",),
                        classes="mt-2",
                        color="cyan darken-3",
                        raw_attrs=[":aria-label=\"patch.name + ' transparency'\""],
                    )
            vuetify.VDivider(classes="my-3")
            html.H3("Quality metrics", classes="text-subtitle-2 font-weight-bold mb-2")
            html.Div(
                "Max non-orthogonality: {{ mesh_quality_max_non_orthogonality == null ? '—' : mesh_quality_max_non_orthogonality + '°' }}",
                classes="text-caption mb-1",
            )
            html.Div(
                "Average non-orthogonality: {{ mesh_quality_average_non_orthogonality == null ? '—' : mesh_quality_average_non_orthogonality + '°' }}",
                classes="text-caption mb-1",
            )
            html.Div(
                "Max skewness: {{ mesh_quality_max_skewness == null ? '—' : mesh_quality_max_skewness }}",
                classes="text-caption mb-1",
            )
            html.Div(
                "Max aspect ratio: {{ mesh_quality_max_aspect_ratio == null ? '—' : mesh_quality_max_aspect_ratio }}",
                classes="text-caption",
            )
