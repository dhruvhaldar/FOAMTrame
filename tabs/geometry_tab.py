from __future__ import annotations

import asyncio
import base64
import gzip
import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

import vtk
from trame.widgets import html, vtk as vtk_widgets, vuetify

from app_state import load_geometry_preferences, update_geometry_preferences
from backend.geometry.library import (
    import_resource_geometry,
    list_case_geometry,
    list_resource_geometry,
)
from tabs.setup_tab import get_docker_client, load_config

logger = logging.getLogger("FOAMTrame")

SUPPORTED_EXTENSIONS = {
    ".vtk",
    ".vtu",
    ".vtp",
    ".vti",
    ".vtr",
    ".vts",
    ".ply",
    ".stl",
    ".obj",
}
READERS = {
    ".vtu": vtk.vtkXMLUnstructuredGridReader,
    ".vtp": vtk.vtkXMLPolyDataReader,
    ".vti": vtk.vtkXMLImageDataReader,
    ".vtr": vtk.vtkXMLRectilinearGridReader,
    ".vts": vtk.vtkXMLStructuredGridReader,
    ".vtk": vtk.vtkDataSetReader,
    ".ply": vtk.vtkPLYReader,
    ".stl": vtk.vtkSTLReader,
    ".obj": vtk.vtkOBJReader,
}

renderer = vtk.vtkRenderer()
renderer.SetBackground(0.72, 0.94, 1.0)
renderer.SetBackground2(0.92, 0.85, 0.91)
renderer.GradientBackgroundOn()
render_window = vtk.vtkRenderWindow()
render_window.SetOffScreenRendering(1)
render_window.AddRenderer(renderer)
render_window.SetMultiSamples(0)
interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(render_window)
interactor_style = vtk.vtkInteractorStyleTrackballCamera()
interactor.SetInteractorStyle(interactor_style)
interactor.GetInteractorStyle().SetCurrentRenderer(renderer)

# Keep a non-visible pipeline attached while no geometry is selected. Some VTK
# backends do not initialise a remote view reliably with a completely empty scene.
placeholder_source = vtk.vtkSphereSource()
placeholder_source.Update()
placeholder_mapper = vtk.vtkPolyDataMapper()
placeholder_mapper.SetInputData(placeholder_source.GetOutput())
placeholder_actor = vtk.vtkActor()
placeholder_actor.SetMapper(placeholder_mapper)
placeholder_actor.SetVisibility(False)
renderer.AddActor(placeholder_actor)

active_actors: list[Any] = []
custom_dataset: list[Any | None] = [None]
custom_display_name = [""]


def _reader_for(path: str | Path):
    extension = Path(path).suffix.lower()
    reader_class = READERS.get(extension)
    if reader_class is None:
        raise ValueError(f"Unsupported extension '{extension}'")
    return reader_class()


def _read_dataset(path: str | Path):
    """Read a VTK-supported dataset, transparently expanding surface .gz files."""
    source = Path(path)
    temporary_path: Path | None = None
    try:
        if source.suffix.lower() == ".gz":
            inner_extension = Path(source.stem).suffix.lower()
            if inner_extension not in {".stl", ".obj", ".ply"}:
                raise ValueError(f"Unsupported compressed geometry '{source.name}'")
            with gzip.open(source, "rb") as compressed:
                with tempfile.NamedTemporaryFile(
                    suffix=inner_extension, delete=False
                ) as expanded:
                    expanded.write(compressed.read())
                    temporary_path = Path(expanded.name)
            reader_path = temporary_path
        else:
            reader_path = source

        reader = _reader_for(reader_path)
        reader.SetFileName(str(reader_path))
        reader.Update()
        output = reader.GetOutputDataObject(0)
        if output is None or not output.IsA("vtkDataSet"):
            raise ValueError(f"{source.name} did not contain a VTK dataset.")
        if output.GetNumberOfPoints() == 0:
            raise ValueError(f"{source.name} contains no points.")
        dataset = output.NewInstance()
        dataset.ShallowCopy(output)
        return dataset
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def setup_geometry_tab(server):
    state, ctrl = server.state, server.controller
    preferences = load_geometry_preferences()
    preferred_mode = preferences["preferred_mode"]
    if not state.active_case and preferred_mode != "custom":
        preferred_mode = "custom"
        # This is an availability fallback, not a change to the user's stored
        # preference. A newly selected case should still return to Case mode.
        preferences["preferred_mode"] = preferred_mode

    state.setdefault("geometry_mode", preferred_mode)
    state.setdefault("geometry_file_name", "No geometry rendered")
    state.setdefault("geometry_dataset_type", "—")
    state.setdefault("geometry_dataset_info", "Choose a custom dataset to begin")
    state.setdefault("geometry_error_message", "")
    state.setdefault("geometry_status_message", "")
    state.setdefault("geometry_upload", None)
    state.setdefault("geometry_library_files", [])
    state.setdefault("geometry_library_selection", preferences["library_selection"])
    state.setdefault("geometry_library_loading", False)
    state.setdefault("geometry_library_importing", False)

    server_event_loop = [None]
    view_ready = [False]
    observed_active_case = [str(state.active_case or "")]
    library_lock = threading.Lock()
    import_lock = threading.Lock()

    def persist_preferences(updates: dict[str, str]) -> None:
        changed = {
            key: value
            for key, value in updates.items()
            if preferences.get(key) != value
        }
        if changed and update_geometry_preferences(changed):
            preferences.update(changed)

    @ctrl.add("on_server_ready")
    def capture_geometry_event_loop(**_):
        server_event_loop[0] = asyncio.get_running_loop()

    @ctrl.add("on_client_connected")
    def enable_geometry_updates(**_):
        view_ready[0] = True
        update_view(reset_camera=bool(active_actors))

    def publish(*keys: str) -> None:
        state.dirty(*keys)
        state.flush()
        loop = server_event_loop[0]
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(server.force_state_push, *keys)

    def update_view(reset_camera: bool = False) -> None:
        if view_ready[0] and ctrl.geometry_view_update.exists():
            if reset_camera:
                renderer.ResetCamera()
            render_window.Render()
            ctrl.geometry_view_update()

    def clear_render(
        info: str = "Choose a custom dataset to begin", *, publish_state: bool = True
    ) -> None:
        for active_actor in active_actors:
            renderer.RemoveActor(active_actor)
        active_actors.clear()
        state.geometry_file_name = "No geometry rendered"
        state.geometry_dataset_type = "—"
        state.geometry_dataset_info = info
        if publish_state:
            publish(
                "geometry_file_name", "geometry_dataset_type", "geometry_dataset_info"
            )
        update_view()

    def render_datasets(
        datasets: list[tuple[str, Any]],
        *,
        file_name: str,
        dataset_type: str,
        info: str,
    ) -> None:
        clear_render(publish_state=False)
        palette = (
            (0.06, 0.72, 0.84),
            (0.05, 0.56, 0.68),
            (0.22, 0.78, 0.72),
            (0.15, 0.45, 0.62),
        )
        for index, (_name, dataset) in enumerate(datasets):
            mapper = vtk.vtkDataSetMapper()
            mapper.SetInputData(dataset)
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(*palette[index % len(palette)])
            renderer.AddActor(actor)
            active_actors.append(actor)
        state.geometry_file_name = file_name
        state.geometry_dataset_type = dataset_type
        state.geometry_dataset_info = info
        state.geometry_error_message = ""
        publish(
            "geometry_file_name",
            "geometry_dataset_type",
            "geometry_dataset_info",
            "geometry_error_message",
        )
        update_view(reset_camera=True)

    def load_custom_dataset(path: str, display_name: str | None = None) -> None:
        try:
            dataset = _read_dataset(path)
            custom_dataset[0] = dataset
            name = display_name or Path(path).name
            custom_display_name[0] = name
            render_datasets(
                [(name, dataset)],
                file_name=name,
                dataset_type=dataset.GetClassName().replace("vtk", ""),
                info=(
                    f"{dataset.GetNumberOfPoints():,} pts · "
                    f"{dataset.GetNumberOfCells():,} cells"
                ),
            )
        except Exception as exc:
            state.geometry_error_message = str(exc)
            publish("geometry_error_message")

    def load_active_case_geometry() -> None:
        active_case = str(state.active_case or "")
        if not active_case:
            clear_render("Select an active case to render its geometry.")
            return
        try:
            config = load_config()
            paths = list_case_geometry(config["CASE_ROOT"], active_case)
            if not paths:
                clear_render(
                    "No supported geometry found in constant/triSurface or "
                    "constant/geometry for this case."
                )
                state.geometry_error_message = ""
                publish("geometry_error_message")
                return

            loaded: list[tuple[str, Any]] = []
            failures: list[str] = []
            points = 0
            cells = 0
            for path in paths:
                try:
                    dataset = _read_dataset(path)
                    loaded.append((path.name, dataset))
                    points += dataset.GetNumberOfPoints()
                    cells += dataset.GetNumberOfCells()
                except Exception as exc:
                    failures.append(f"{path.name}: {exc}")
            if not loaded:
                raise ValueError("No case geometry file could be rendered.")

            count = len(loaded)
            render_datasets(
                loaded,
                file_name=f"{active_case} · {count} surface{'s' if count != 1 else ''}",
                dataset_type="Case geometry",
                info=f"{points:,} pts · {cells:,} cells",
            )
            if failures:
                state.geometry_error_message = (
                    f"Rendered {count} file(s); {len(failures)} could not be read. "
                    + " ".join(failures)
                )
                publish("geometry_error_message")
        except Exception as exc:
            clear_render("Case geometry could not be loaded.")
            state.geometry_error_message = str(exc)
            publish("geometry_error_message")

    ctrl.reload_case_geometry = load_active_case_geometry

    def render_custom_or_empty() -> None:
        dataset = custom_dataset[0]
        if dataset is None:
            clear_render()
            return
        render_datasets(
            [(custom_display_name[0], dataset)],
            file_name=custom_display_name[0],
            dataset_type=dataset.GetClassName().replace("vtk", ""),
            info=(
                f"{dataset.GetNumberOfPoints():,} pts · "
                f"{dataset.GetNumberOfCells():,} cells"
            ),
        )

    def change_mode(mode: str) -> None:
        if mode not in {"case", "custom", "library"}:
            return
        if mode in {"case", "library"} and not state.active_case:
            mode = "custom"
        state.geometry_mode = mode

    ctrl.set_geometry_mode = change_mode

    def clear_and_use_custom() -> None:
        custom_dataset[0] = None
        custom_display_name[0] = ""
        state.geometry_mode = "custom"

    ctrl.clear_and_use_custom_geometry = clear_and_use_custom

    def clear_custom_render() -> None:
        custom_dataset[0] = None
        custom_display_name[0] = ""
        clear_render()

    ctrl.clear_geometry_render = clear_custom_render

    @state.change("geometry_mode")
    def on_geometry_mode_change(geometry_mode, **_):
        mode = str(geometry_mode or "custom")
        if mode in {"case", "library"} and not state.active_case:
            state.geometry_mode = "custom"
            mode = "custom"
        persist_preferences({"preferred_mode": mode})
        if mode == "custom":
            state.geometry_status_message = ""
            state.geometry_error_message = ""
            publish("geometry_status_message", "geometry_error_message")
            render_custom_or_empty()
        else:
            load_active_case_geometry()
            if mode == "library":
                ctrl.refresh_geometry_library()

    @state.change("active_case")
    def on_active_case_change_geometry(active_case, **_):
        active_case = str(active_case or "")
        if active_case == observed_active_case[0]:
            return
        observed_active_case[0] = active_case
        if not active_case:
            state.geometry_mode = "custom"
            clear_render()
            return
        state.geometry_mode = "case"
        persist_preferences({"preferred_mode": "case"})
        load_active_case_geometry()

    def refresh_geometry_library() -> None:
        if not library_lock.acquire(blocking=False):
            return
        state.geometry_library_loading = True
        state.geometry_status_message = (
            "Loading geometry resources from the OpenFOAM image…"
        )
        publish("geometry_library_loading", "geometry_status_message")

        def worker() -> None:
            try:
                config = load_config()
                files = list_resource_geometry(
                    get_docker_client(),
                    config["DOCKER_IMAGE"],
                    config["OPENFOAM_VERSION"],
                )
                state.geometry_library_files = files
                if state.geometry_library_selection not in files:
                    state.geometry_library_selection = ""
                state.geometry_status_message = (
                    f"Found {len(files)} geometry resource(s)."
                    if files
                    else "The configured image contains no supported geometry resources."
                )
                state.geometry_error_message = ""
            except Exception as exc:
                state.geometry_library_files = []
                state.geometry_error_message = (
                    f"Could not load the geometry library: {exc}"
                )
                state.geometry_status_message = ""
            finally:
                state.geometry_library_loading = False
                publish(
                    "geometry_library_files",
                    "geometry_library_selection",
                    "geometry_library_loading",
                    "geometry_status_message",
                    "geometry_error_message",
                )
                library_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    ctrl.refresh_geometry_library = refresh_geometry_library

    @state.change("geometry_library_selection")
    def persist_library_selection(geometry_library_selection, **_):
        persist_preferences(
            {"library_selection": str(geometry_library_selection or "")}
        )

    def import_selected_library_geometry() -> None:
        if not state.active_case or not state.geometry_library_selection:
            return
        if not import_lock.acquire(blocking=False):
            return
        state.geometry_library_importing = True
        state.geometry_status_message = (
            f"Importing {state.geometry_library_selection} into {state.active_case}…"
        )
        publish("geometry_library_importing", "geometry_status_message")

        def worker() -> None:
            try:
                config = load_config()
                imported = import_resource_geometry(
                    get_docker_client(),
                    config["DOCKER_IMAGE"],
                    config["OPENFOAM_VERSION"],
                    config["CASE_ROOT"],
                    str(state.active_case),
                    str(state.geometry_library_selection),
                )
                state.geometry_status_message = (
                    f"Imported {imported.name} into constant/triSurface."
                )
                state.geometry_error_message = ""
                load_active_case_geometry()
            except Exception as exc:
                state.geometry_error_message = f"Geometry import failed: {exc}"
                state.geometry_status_message = ""
            finally:
                state.geometry_library_importing = False
                publish(
                    "geometry_library_importing",
                    "geometry_status_message",
                    "geometry_error_message",
                )
                import_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    ctrl.import_library_geometry = import_selected_library_geometry

    def reset_geometry_camera() -> None:
        if ctrl.geometry_view_reset_camera.exists():
            ctrl.geometry_view_reset_camera()

    ctrl.reset_geometry_camera = reset_geometry_camera

    def _uploaded_bytes(file_value: Any) -> tuple[str, bytes]:
        item = (
            file_value[0]
            if isinstance(file_value, (list, tuple)) and file_value
            else file_value
        )
        name = "dataset.vtk"
        content = None
        if isinstance(item, dict):
            name = item.get("name") or item.get("filename") or name
            content = item.get("content")
        elif hasattr(item, "name") or hasattr(item, "content"):
            name = (
                getattr(item, "name", None) or getattr(item, "filename", None) or name
            )
            content = getattr(item, "content", None)
        elif isinstance(item, (bytes, str)):
            content = item
        if content is None:
            raise ValueError("Invalid upload payload")
        if isinstance(content, bytes):
            return name, content
        if isinstance(content, str):
            encoded = (
                content.split(",", 1)[-1] if content.startswith("data:") else content
            )
            try:
                return name, base64.b64decode(encoded, validate=True)  # nosec
            except Exception:
                return name, content.encode("utf-8")
        if isinstance(content, (list, tuple)):
            return name, bytes(content)
        raise ValueError("Unsupported upload content")

    @state.change("geometry_upload")
    def on_geometry_upload(geometry_upload, **_):
        if not geometry_upload:
            return
        temporary_path: Path | None = None
        try:
            name, content = _uploaded_bytes(geometry_upload)
            extension = Path(name).suffix.lower()
            if extension not in SUPPORTED_EXTENSIONS:
                raise ValueError(f"Unsupported file type '{extension}'")
            with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as upload:
                upload.write(content)
                temporary_path = Path(upload.name)
            state.geometry_file_name = name
            load_custom_dataset(str(temporary_path), name)
        except Exception as exc:
            state.geometry_error_message = str(exc)
            publish("geometry_error_message")
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            state.geometry_upload = None
            publish("geometry_upload")

    if state.active_case and state.geometry_mode in {"case", "library"}:
        load_active_case_geometry()
    else:
        clear_render()


def build_geometry_drawer():
    from trame.app import get_server

    server = get_server()
    assert server is not None
    ctrl = server.controller
    with html.Div(v_show="active_tab === 1", classes="pa-4 geometry-drawer"):
        html.Div(
            "Geometry workspace",
            classes="text-subtitle-1 font-weight-bold text-slate-800 mb-1",
        )
        html.Div(
            "Render case surfaces, inspect a custom dataset, or import from OpenFOAM.",
            classes="text-caption text--secondary mb-3",
        )
        with vuetify.VBtnToggle(
            v_model=("geometry_mode",),
            mandatory=True,
            dense=True,
            classes="geometry-mode-toggle mb-4",
        ):
            vuetify.VBtn("Case", value="case", disabled=("!active_case",))
            vuetify.VBtn("Custom", value="custom")
            vuetify.VBtn("Library", value="library", disabled=("!active_case",))

        with html.Div(v_if="geometry_mode === 'case'", classes="geometry-mode-panel"):
            html.Div("Active case geometry", classes="font-weight-bold mb-1")
            html.Div(
                "{{ active_case || 'No active case' }}",
                classes="text-cyan-900 text-body-2 mb-2",
            )
            html.Div(
                "Renders supported surfaces from constant/triSurface, falling back "
                "to constant/geometry.",
                classes="text-caption text--secondary mb-3",
            )
            vuetify.VBtn(
                "Reload case geometry",
                click=ctrl.reload_case_geometry,
                block=True,
                classes="theme-btn-primary mb-2",
            )
            vuetify.VBtn(
                "Clear & use custom dataset",
                click=ctrl.clear_and_use_custom_geometry,
                block=True,
                outlined=True,
                classes="geometry-secondary-button geometry-clear-custom-button",
            )

        with html.Div(v_if="geometry_mode === 'custom'", classes="geometry-mode-panel"):
            html.Div("Custom dataset", classes="font-weight-bold mb-1")
            html.Div(
                "Uploads are session-only and are not copied into an OpenFOAM case.",
                classes="text-caption text--secondary mb-3",
            )
            vuetify.VFileInput(
                label="Choose geometry dataset",
                v_model=("geometry_upload", None),
                accept=".vtk,.vtu,.vtp,.vti,.vtr,.vts,.ply,.stl,.obj",
                dense=True,
                outlined=True,
                hide_details=True,
                prepend_icon="mdi-cube-scan",
                classes="mb-3",
            )
            vuetify.VBtn(
                "Clear render",
                click=ctrl.clear_geometry_render,
                block=True,
                outlined=True,
                classes="geometry-secondary-button",
            )

        with html.Div(
            v_if="geometry_mode === 'library'", classes="geometry-mode-panel"
        ):
            html.Div("OpenFOAM geometry library", classes="font-weight-bold mb-1")
            html.Div(
                "Browse $FOAM_TUTORIALS/\u200bresources/\u200bgeometry in the configured image and import into the active case.",
                classes="geometry-library-description text-caption text--secondary mb-3",
            )
            vuetify.VSelect(
                label="Select geometry",
                v_model=("geometry_library_selection", ""),
                items=("geometry_library_files", []),
                loading=("geometry_library_loading", False),
                disabled=("geometry_library_loading", False),
                dense=True,
                outlined=True,
                hide_details=True,
                classes="geometry-library-select mb-3",
            )
            with vuetify.VRow(dense=True, classes="mb-1"):
                with vuetify.VCol(cols=5):
                    vuetify.VBtn(
                        "Refresh",
                        click=ctrl.refresh_geometry_library,
                        block=True,
                        outlined=True,
                        loading=("geometry_library_loading", False),
                        classes="geometry-secondary-button",
                    )
                with vuetify.VCol(cols=7):
                    vuetify.VBtn(
                        "Import to case",
                        click=ctrl.import_library_geometry,
                        block=True,
                        loading=("geometry_library_importing", False),
                        disabled=(
                            "!geometry_library_selection || geometry_library_loading",
                        ),
                        classes="theme-btn-primary",
                    )

        vuetify.VAlert(
            "{{ geometry_status_message }}",
            v_if="geometry_status_message",
            type="info",
            dense=True,
            outlined=True,
            classes="mt-3 mb-2",
            aria_live="polite",
        )
        vuetify.VAlert(
            "{{ geometry_error_message }}",
            v_if="geometry_error_message",
            type="error",
            dense=True,
            outlined=True,
            classes="mt-3 mb-2",
            aria_live="polite",
        )
        with html.Div(classes="geometry-dataset-summary mt-4"):
            html.Div(
                "{{ geometry_file_name }}",
                classes="text-subtitle-2 font-weight-bold text-cyan-900",
            )
            html.Div(
                "{{ geometry_dataset_type }}", classes="text-caption text--secondary"
            )
            html.Div(
                "{{ geometry_dataset_info }}", classes="text-caption text--secondary"
            )
        vuetify.VBtn(
            "Reset Camera",
            click=ctrl.reset_geometry_camera,
            block=True,
            classes="theme-btn-primary mt-4",
            disabled=("geometry_file_name === 'No geometry rendered'",),
        )


def build_geometry_content():
    from trame.app import get_server

    server = get_server()
    assert server is not None
    ctrl = server.controller
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-0 geometry-viewer",
        v_if="active_tab === 1",
    ):
        with html.Div(
            v_if="geometry_file_name === 'No geometry rendered'",
            classes="geometry-empty-state",
            role="status",
        ):
            vuetify.VIcon("mdi-cube-off-outline", size=58, color="blue-grey lighten-2")
            html.H2("No geometry rendered", classes="text-h6 mt-3 mb-1")
            html.P("{{ geometry_dataset_info }}", classes="text-body-2 mb-0")
        view = vtk_widgets.VtkRemoteLocalView(
            render_window,
            interactive_ratio=1,
            classes="fill-height w-100",
        )
        ctrl.geometry_view_update = view.update
        ctrl.geometry_view_reset_camera = view.reset_camera
