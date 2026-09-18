"""Guided physics authoring and named mesh-patch inspection."""

import asyncio
from dataclasses import asdict
from pathlib import Path

import vtk
from trame.widgets import client, html, vtk as vtk_widgets, vuetify

from backend.geometry.library import resolve_case_path
from backend.meshing.inspection import inspect_case_mesh
from backend.meshing.reader import read_mesh_patches
from backend.physics import (
    Boundary,
    Physics,
    PhysicsPlan,
    apply_physics,
    load_physics,
    plan_physics,
)


renderer = vtk.vtkRenderer()
renderer.SetBackground(0.87, 0.94, 0.96)
window = vtk.vtkRenderWindow()
window.SetOffScreenRendering(1)
window.AddRenderer(renderer)
interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(window)
interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())


def setup_physics_tab(server):
    state, ctrl = server.state, server.controller
    defaults = {
        "physics_message": "Select an active case to configure physics.",
        "physics_error": False,
        "physics_patches": [],
        "physics_selected": "",
        "physics_role": "unassigned",
        "physics_roles": [],
        "physics_ux": 0,
        "physics_uy": 0,
        "physics_uz": 0,
        "physics_pressure": 0,
        "physics_initial_x": 0,
        "physics_initial_y": 0,
        "physics_initial_z": 0,
        "physics_preview": [],
        "physics_review_dialog": False,
        "physics_busy": False,
        "physics_view_message": "Generate a mesh to inspect boundary patches.",
    }
    for key, value in asdict(Physics()).items():
        if key not in ("version", "initial_velocity"):
            defaults[f"physics_{key}"] = value
    for key, value in defaults.items():
        state.setdefault(key, value)
    draft: dict[str, Boundary] = {}
    actors: dict[str, vtk.vtkActor] = {}
    reviewed: list[PhysicsPlan | None] = [None]
    loaded_case: list[Path | None] = [None]
    draft_case: list[Path | None] = [None]
    event_loop: list[asyncio.AbstractEventLoop | None] = [None]

    @ctrl.add("on_server_ready")
    def capture_loop(**_):
        event_loop[0] = asyncio.get_running_loop()

    def publish():
        state.flush()
        server.force_state_push(*defaults)

    def case_path() -> Path | None:
        if not state.active_case:
            return None
        return resolve_case_path(str(state.case_root), str(state.active_case))

    def busy() -> bool:
        case = case_path()
        return bool(
            case
            and any(
                Path(item.get("case_path", "")).resolve() == case
                for item in list(state.simulation_queue or [])
            )
        )

    def refresh_view(**_):
        case = case_path()
        if int(state.active_tab or 0) != 3 or busy() or not case:
            return
        if not inspect_case_mesh(case).available:
            state.physics_view_message = "Generate a mesh in Meshing first."
            if ctrl.physics_view_update.exists():
                ctrl.physics_view_update()
            return
        try:
            if loaded_case[0] != case:
                datasets = ctrl.with_idle_case(case, lambda: read_mesh_patches(case))
                renderer.RemoveAllViewProps()
                actors.clear()
                for name, data in datasets.items():
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(data)
                    mapper.ScalarVisibilityOff()
                    actor = vtk.vtkActor()
                    actor.SetMapper(mapper)
                    renderer.AddActor(actor)
                    actors[name] = actor
                loaded_case[0] = case
                renderer.ResetCamera()
            for name, actor in actors.items():
                selected = name == state.physics_selected
                actor.GetProperty().SetColor(
                    *((1.0, 0.65, 0.15) if selected else (0.12, 0.5, 0.58))
                )
                actor.GetProperty().SetOpacity(1 if selected else 0.25)
            state.physics_view_message = (
                "Selected patch is highlighted; other patches are translucent."
            )
            if ctrl.physics_view_update.exists():
                ctrl.physics_view_update()
        except (ValueError, OSError) as exc:
            state.physics_view_message = str(exc)

    def publish_boundaries():
        case = case_path()
        mesh_patches = inspect_case_mesh(case).patches
        state.physics_patches = [
            {
                "name": p.name,
                "type": p.patch_type,
                "faces": p.face_count,
                "role": draft[p.name].role if p.name in draft else "unassigned",
            }
            for p in mesh_patches
        ]

    @state.change("physics_selected")
    def select_patch(**_):
        item = draft.get(state.physics_selected)
        if item:
            patch = next(
                (p for p in state.physics_patches if p["name"] == item.name), None
            )
            roles = {
                "wall": ["wall", "movingWall"],
                "patch": ["inlet", "outlet", "slip"],
                "empty": ["empty"],
                "symmetry": ["symmetry"],
                "symmetryPlane": ["symmetryPlane"],
            }
            state.physics_roles = roles.get(patch["type"], []) if patch else []
            state.physics_role = item.role
            state.physics_ux, state.physics_uy, state.physics_uz = item.velocity
            state.physics_pressure = item.pressure
        refresh_view()

    def reload_case(**_):
        reviewed[0] = None
        state.physics_review_dialog = False
        loaded_case[0] = None
        renderer.RemoveAllViewProps()
        actors.clear()
        draft.clear()
        state.physics_patches = []
        state.physics_selected = ""
        state.physics_roles = []
        state.physics_role = "unassigned"
        state.physics_ux = state.physics_uy = state.physics_uz = 0
        state.physics_pressure = 0
        state.physics_error = False
        state.physics_busy = busy()
        case = case_path()
        draft_case[0] = case
        if not case:
            state.physics_patches = []
            state.physics_message = "Create or select a case in Setup, then add geometry and generate a mesh."
            return
        if busy():
            state.physics_message = (
                "Case is queued or running. Physics edits are disabled."
            )
            return
        try:
            model, boundaries = ctrl.with_idle_case(
                case, lambda: load_physics(case, str(state.openfoam_version))
            )
            for key, value in asdict(model).items():
                if key not in ("version", "initial_velocity"):
                    state[f"physics_{key}"] = value
            (
                state.physics_initial_x,
                state.physics_initial_y,
                state.physics_initial_z,
            ) = model.initial_velocity
            draft.update({b.name: b for b in boundaries})
            state.physics_message = "Assign each patch, review the file changes, then save. Unassigned patches prevent saving."
            if not boundaries:
                state.physics_message = (
                    "This case needs a mesh. Continue with Geometry and Meshing first."
                )
        except (ValueError, OSError, UnicodeError) as exc:
            state.physics_message = str(exc)
            state.physics_error = True
        publish_boundaries()
        state.physics_selected = next(iter(draft), "")
        select_patch()

    def assign_boundary():
        try:
            if busy():
                raise ValueError(
                    "Wait for this case's queued or running job to finish."
                )
            if state.physics_selected not in draft:
                raise ValueError("Select a patch first.")
            draft[state.physics_selected] = Boundary(
                str(state.physics_selected),
                str(state.physics_role),
                (
                    float(state.physics_ux),
                    float(state.physics_uy),
                    float(state.physics_uz),
                ),
                float(state.physics_pressure),
            )
            publish_boundaries()
            state.physics_message = f"{state.physics_selected} assigned in the draft. Review & save to update the case files."
            state.physics_error = False
        except (ValueError, TypeError) as exc:
            state.physics_message, state.physics_error = str(exc), True

    def review():
        try:
            case = case_path()
            if not case:
                raise ValueError("Select an active case first.")
            model = Physics(
                version=str(state.openfoam_version),
                regime=str(state.physics_regime),
                turbulence=str(state.physics_turbulence),
                nu=float(state.physics_nu),
                initial_velocity=(
                    float(state.physics_initial_x),
                    float(state.physics_initial_y),
                    float(state.physics_initial_z),
                ),
                initial_pressure=float(state.physics_initial_pressure),
                k=float(state.physics_k),
                omega=float(state.physics_omega),
                end_time=float(state.physics_end_time),
                delta_t=float(state.physics_delta_t),
                write_interval=float(state.physics_write_interval),
            )
            plan = ctrl.with_idle_case(
                case, lambda: plan_physics(case, model, list(draft.values()))
            )
            reviewed[0] = plan
            state.physics_preview = plan.preview()
            state.physics_review_dialog = True
            state.physics_error = False
        except (ValueError, TypeError, OSError, UnicodeError) as exc:
            state.physics_message, state.physics_error = str(exc), True

    def save():
        state.physics_review_dialog = False
        plan = reviewed[0]
        reviewed[0] = None
        try:
            if (
                plan is None
                or plan.case != case_path()
                or plan.version != str(state.openfoam_version)
            ):
                raise ValueError(
                    "Case or runtime changed. Review the configuration again."
                )
            backup = ctrl.with_idle_case(plan.case, lambda: apply_physics(plan))
            state.physics_message = f"Physics saved. Previous files backed up in {backup.relative_to(plan.case)}. Open Run/Log to inspect available solver actions."
            state.physics_error = False
        except (ValueError, OSError) as exc:
            state.physics_message, state.physics_error = str(exc), True
        state.flush()
        server.force_state_push(
            "physics_review_dialog", "physics_message", "physics_error"
        )
        if not state.physics_error:
            ctrl.scan_case_capabilities()

    @state.change("active_case", "case_root", "openfoam_version")
    def case_changed(**_):
        def reload_and_publish():
            reload_case()
            publish()

        loop = event_loop[0]
        if loop is not None:
            loop.call_soon_threadsafe(reload_and_publish)
        else:
            reload_case()

    @state.change("simulation_queue")
    def queue_changed(**_):
        def update_queue_state():
            was_busy = state.physics_busy
            state.physics_busy = busy()
            if was_busy and not state.physics_busy:
                reload_case()
            publish()

        loop = event_loop[0]
        if loop is not None:
            loop.call_soon_threadsafe(update_queue_state)
        else:
            state.physics_busy = busy()

    @state.change("active_tab")
    def tab_changed(**_):
        if int(state.active_tab or 0) == 3:
            # A mesh may have been created since this workspace last loaded.
            if not draft or draft_case[0] != case_path():
                reload_case()
            refresh_view()
            publish()

    ctrl.physics_reload = reload_case
    ctrl.physics_assign = assign_boundary
    ctrl.physics_review = review
    ctrl.physics_save = save
    ctrl.physics_refresh_view = refresh_view
    ctrl.physics_reset_camera = lambda: (renderer.ResetCamera(), refresh_view())


def _number_input(key: str, label: str):
    vuetify.VTextField(
        v_model=(key,),
        label=label,
        type="number",
        outlined=True,
        dense=True,
        hide_details=True,
        classes="mb-3",
        disabled=("physics_busy",),
    )


def build_physics_drawer():
    from trame.app import get_server

    server = get_server()
    assert server is not None
    ctrl = server.controller
    with html.Div(v_show="active_tab === 3", classes="pa-4"):
        html.H2("Physics workspace", classes="text-h6 mb-2")
        html.P(
            "Single-region incompressible flow. Values use SI units.",
            classes="text-body-2",
        )
        with vuetify.VCard(classes="glass-card pa-3 mb-3"):
            html.H3("Flow & material", classes="text-subtitle-1 mb-3")
            vuetify.VSelect(
                v_model=("physics_regime",),
                items=(["steady", "transient"],),
                label="Time model",
                outlined=True,
                dense=True,
                disabled=("physics_busy",),
            )
            vuetify.VSelect(
                v_model=("physics_turbulence",),
                items=(["laminar", "kOmegaSST"],),
                label="Turbulence",
                outlined=True,
                dense=True,
                disabled=("physics_busy",),
            )
            with html.Div(classes="d-flex flex-wrap mb-3"):
                vuetify.VBtn(
                    "Air ≈20°C",
                    small=True,
                    text=True,
                    click="physics_nu = 0.000015",
                    disabled=("physics_busy",),
                )
                vuetify.VBtn(
                    "Water ≈20°C",
                    small=True,
                    text=True,
                    click="physics_nu = 0.000001",
                    disabled=("physics_busy",),
                )
            _number_input("physics_nu", "Kinematic viscosity ν (m²/s)")
        with vuetify.VCard(classes="glass-card pa-3 mb-3"):
            html.H3("Initial fields", classes="text-subtitle-1 mb-3")
            for axis in ("x", "y", "z"):
                _number_input(f"physics_initial_{axis}", f"Initial U{axis} (m/s)")
            _number_input("physics_initial_pressure", "Initial p/ρ (m²/s²)")
            with html.Div(v_if="physics_turbulence === 'kOmegaSST'"):
                _number_input("physics_k", "Initial / inlet k (m²/s²)")
                _number_input("physics_omega", "Initial / inlet ω (1/s)")
                html.P(
                    "Wall functions need suitable near-wall mesh resolution. Check y+ after solving.",
                    classes="text-caption",
                )
        with vuetify.VCard(classes="glass-card pa-3 mb-3"):
            html.H3("Numerical controls", classes="text-subtitle-1 mb-3")
            _number_input("physics_end_time", "End time / steady iterations")
            _number_input("physics_delta_t", "Time step (s; steady: use 1)")
            _number_input("physics_write_interval", "Write every N steps")
            html.P(
                "Conservative upwind convection; fixed time step. Review convergence and Courant number during the run.",
                classes="text-caption",
            )
        vuetify.VBtn(
            "Reload saved physics",
            block=True,
            outlined=True,
            click=ctrl.physics_reload,
            disabled=("physics_busy",),
            classes="mb-2",
        )
        vuetify.VBtn(
            "Review & save",
            block=True,
            color="cyan darken-3",
            dark=True,
            click=ctrl.physics_review,
            disabled=("physics_busy || !physics_patches.length",),
        )


def build_physics_content():
    from trame.app import get_server

    server = get_server()
    assert server is not None
    ctrl = server.controller
    with vuetify.VContainer(
        v_if="active_tab === 3",
        fluid=True,
        classes="pa-4",
        style="height:100%;overflow:auto",
    ):
        with vuetify.VCard(classes="glass-card pa-4 mb-4"):
            html.H2("Physics & boundary conditions", classes="text-h5 mb-2")
            html.P(
                "{{ physics_message }}",
                raw_attrs=['role="status"', 'aria-live="polite"'],
                classes=("physics_error ? 'error--text mb-2' : 'mb-2'",),
            )
            html.P(
                "{{ physics_busy ? 'Editing locked while this case is queued or running.' : 'Changes remain a draft until you review and save the files.' }}",
                classes="text-caption mb-0",
            )
            with html.Div(classes="d-flex flex-wrap mt-2", style="gap:8px"):
                vuetify.VBtn(
                    "Meshing", small=True, outlined=True, click="active_tab = 2"
                )
                vuetify.VBtn(
                    "Run / Log", small=True, outlined=True, click="active_tab = 4"
                )
        with vuetify.VRow():
            with vuetify.VCol(cols=12, md=7):
                with vuetify.VCard(classes="glass-card pa-3"):
                    html.H3("Select a named patch", classes="text-subtitle-1 mb-2")
                    vuetify.VSelect(
                        v_model=("physics_selected",),
                        items=("physics_patches",),
                        item_text="name",
                        item_value="name",
                        label="Mesh patch",
                        outlined=True,
                        dense=True,
                        disabled=("physics_busy",),
                    )
                    with html.Div(
                        style="height:360px;position:relative;overflow:hidden;border-radius:12px"
                    ):
                        view = vtk_widgets.VtkRemoteView(window, ref="physics_view")
                        ctrl.physics_view_update = view.update
                        client.ClientTriggers(
                            ref="physics_mount", mounted=ctrl.physics_refresh_view
                        )
                    html.P("{{ physics_view_message }}", classes="text-caption mt-2")
                    vuetify.VBtn(
                        "Fit view",
                        small=True,
                        text=True,
                        click=ctrl.physics_reset_camera,
                        disabled=("physics_busy || !physics_patches.length",),
                    )
            with vuetify.VCol(cols=12, md=5):
                with vuetify.VCard(classes="glass-card pa-4"):
                    html.H3("Boundary assignment", classes="text-subtitle-1 mb-3")
                    vuetify.VSelect(
                        v_model=("physics_role",),
                        items=("physics_roles",),
                        label="Patch role",
                        outlined=True,
                        dense=True,
                        disabled=("physics_busy || !physics_selected",),
                    )
                    with html.Div(
                        v_if="physics_role === 'inlet' || physics_role === 'movingWall'"
                    ):
                        for axis in ("x", "y", "z"):
                            _number_input(f"physics_u{axis}", f"Velocity {axis} (m/s)")
                    with html.Div(v_if="physics_role === 'outlet'"):
                        _number_input("physics_pressure", "Outlet p/ρ (m²/s²)")
                    html.P(
                        "Pressure is kinematic pressure, not Pa. Wall and symmetry roles must match the mesh patch type.",
                        classes="text-caption",
                    )
                    vuetify.VBtn(
                        "Assign boundary",
                        block=True,
                        color="cyan darken-3",
                        dark=True,
                        click=ctrl.physics_assign,
                        disabled=("physics_busy || !physics_selected",),
                    )
                    vuetify.VDivider(classes="my-3")
                    with html.Div(
                        v_for="patch in physics_patches",
                        key=("patch.name",),
                        classes="py-2",
                        style="border-bottom:1px solid #cce0e5;overflow-wrap:anywhere",
                    ):
                        html.Strong("{{ patch.name }}")
                        html.Div(
                            "{{ patch.type }} · {{ patch.faces }} faces · {{ patch.role }}",
                            classes="text-caption",
                        )
        with vuetify.VDialog(
            v_model=("physics_review_dialog", False),
            max_width="1000",
            scrollable=True,
            raw_attrs=['aria-labelledby="physics-review-title"'],
        ):
            with vuetify.VCard(classes="glass-card capability-dialog"):
                with vuetify.VCardTitle():
                    html.H2(
                        "Review physics files",
                        id="physics-review-title",
                        classes="text-h6",
                    )
                with vuetify.VCardText(style="max-height:65vh;overflow:auto"):
                    html.P(
                        "Existing files are backed up. Unrelated entries are retained. Saving starts future runs at time 0; existing results and Allrun scripts are preserved."
                    )
                    with html.Details(
                        v_for="file in physics_preview",
                        key=("file.path",),
                        classes="mb-3",
                    ):
                        html.Summary("{{ file.path }}", classes="font-weight-bold")
                        html.Pre(
                            "{{ file.diff }}",
                            style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px",
                        )
                        with html.Details():
                            html.Summary("Generated dictionary")
                            html.Pre(
                                "{{ file.content }}",
                                style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px",
                            )
                with vuetify.VCardActions():
                    vuetify.VSpacer()
                    vuetify.VBtn(
                        "Cancel", text=True, click="physics_review_dialog = false"
                    )
                    vuetify.VBtn(
                        "Save physics",
                        color="cyan darken-3",
                        dark=True,
                        click=ctrl.physics_save,
                        disabled=("physics_busy",),
                    )
