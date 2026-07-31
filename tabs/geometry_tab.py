import base64
import os
import tempfile
from pathlib import Path
import requests
import threading
import vtk
from trame.widgets import html, vtk as vtk_widgets, vuetify

from tabs.setup_tab import FLASK_URL

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

# --- VTK Pipeline ---
renderer = vtk.vtkRenderer()
renderer.SetBackground(0.055, 0.075, 0.11)
render_window = vtk.vtkRenderWindow()
render_window.SetOffScreenRendering(1)
render_window.AddRenderer(renderer)
render_window.SetMultiSamples(0)
interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(render_window)
interactor_style = vtk.vtkInteractorStyleTrackballCamera()
interactor.SetInteractorStyle(interactor_style)
interactor.GetInteractorStyle().SetCurrentRenderer(renderer)

# Keep track of active actor
active_actor = [None]


def _reader_for(p: str):
    ext = Path(p).suffix.lower()
    r_cls = READERS.get(ext)
    if not r_cls:
        raise ValueError(f"Unsupported extension '{ext}'")
    return r_cls()


def setup_geometry_tab(server):
    state, ctrl = server.state, server.controller

    # State variables
    state.setdefault("geometry_file_name", "No dataset loaded")
    state.setdefault("geometry_dataset_type", "—")
    state.setdefault("geometry_dataset_info", "Select or import a case to visualize")
    state.setdefault("geometry_error_message", "")
    state.setdefault("geometry_upload", None)

    # Initialise pipeline with a dummy sphere so VTK does not complain at startup
    dummy_source = vtk.vtkSphereSource()
    dummy_source.Update()
    dummy_data = dummy_source.GetOutput()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(dummy_data)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    renderer.AddActor(actor)
    active_actor[0] = actor

    def reset_geometry_camera():
        if hasattr(ctrl, "geometry_view_reset_camera"):
            ctrl.geometry_view_reset_camera()
    ctrl.reset_geometry_camera = reset_geometry_camera

    def load_geometry_dataset(path: str, display_name: str | None = None):
        try:
            reader = _reader_for(path)
            reader.SetFileName(path)
            reader.Update()
            output = reader.GetOutputDataObject(0)
            if output is None or not output.IsA("vtkDataSet"):
                raise ValueError("File did not contain a VTK dataset.")
            if output.GetNumberOfPoints() == 0:
                raise ValueError("Dataset contains no points.")

            ds = output.NewInstance()
            ds.ShallowCopy(output)

            # Update mapper and actor
            new_mapper = vtk.vtkDataSetMapper()
            new_mapper.SetInputData(ds)
            new_actor = vtk.vtkActor()
            new_actor.SetMapper(new_mapper)
            new_actor.GetProperty().SetColor(0.06, 0.72, 0.84)

            if active_actor[0]:
                renderer.RemoveActor(active_actor[0])

            renderer.AddActor(new_actor)
            active_actor[0] = new_actor

            state.geometry_file_name = display_name or Path(path).name
            state.geometry_dataset_type = ds.GetClassName().replace("vtk", "")
            state.geometry_dataset_info = f"{ds.GetNumberOfPoints():,} pts · {ds.GetNumberOfCells():,} cells"
            state.geometry_error_message = ""
            state.flush()

            renderer.ResetCamera()
            render_window.Render()
            if hasattr(ctrl, "geometry_view_update"):
                ctrl.geometry_view_update()
        except Exception as exc:
            state.geometry_error_message = str(exc)
            state.flush()

    # Listen to active_case change to resolve and load VTK automatically
    @state.change("active_case")
    def on_active_case_change_geometry(active_case, **_):
        if not active_case:
            state.geometry_file_name = "No dataset loaded"
            state.geometry_dataset_type = "—"
            state.geometry_dataset_info = "Choose or import a case to visualize"
            state.geometry_error_message = ""
            # Revert to dummy sphere
            if active_actor[0]:
                renderer.RemoveActor(active_actor[0])
            renderer.AddActor(actor)
            active_actor[0] = actor
            state.flush()
            if hasattr(ctrl, "geometry_view_update"):
                ctrl.geometry_view_update()
            return

        def resolve_and_load():
            try:
                res = requests.get(f"{FLASK_URL}/api/case/resolve_vtk", params={"caseName": active_case}, timeout=5).json()
                file_path = res.get("file_path")
                if file_path:
                    load_geometry_dataset(file_path, res.get("file_name"))
                else:
                    state.geometry_file_name = "No dataset loaded"
                    state.geometry_dataset_type = "—"
                    state.geometry_dataset_info = res.get("message", "No VTK mesh file found in case directory.")
                    state.geometry_error_message = ""
                    if active_actor[0]:
                        renderer.RemoveActor(active_actor[0])
                    renderer.AddActor(actor)
                    active_actor[0] = actor
                    state.flush()
                    if hasattr(ctrl, "geometry_view_update"):
                        ctrl.geometry_view_update()
            except Exception as e:
                state.geometry_error_message = f"Error resolving case VTK: {e}"
                state.flush()

        threading.Thread(target=resolve_and_load, daemon=True).start()

    def _uploaded_bytes(file_value):
        item = file_value
        if isinstance(file_value, (list, tuple)) and len(file_value) > 0:
            item = file_value[0]
        name = "dataset.vtk"
        content = None
        if isinstance(item, dict):
            name = item.get("name") or item.get("filename") or name
            content = item.get("content")
        elif hasattr(item, "name") or hasattr(item, "content"):
            name = getattr(item, "name", None) or getattr(item, "filename", None) or name
            content = getattr(item, "content", None)
        elif isinstance(item, (bytes, str)):
            content = item
        if content is None:
            raise ValueError("Invalid upload payload")
        if isinstance(content, bytes):
            return name, content
        if isinstance(content, str):
            encoded = content.split(",", 1)[-1] if content.startswith("data:") else content
            try:
                return name, base64.b64decode(encoded)
            except Exception:
                return name, content.encode("utf-8")
        if isinstance(content, (list, tuple)):
            return name, bytes(content)
        raise ValueError("Unsupported upload content")

    @state.change("geometry_upload")
    def on_geometry_upload(geometry_upload, **_):
        if not geometry_upload:
            return
        try:
            name, content = _uploaded_bytes(geometry_upload)
            ext = Path(name).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise ValueError(f"Unsupported file type '{ext}'")
            h = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            h.write(content)
            h.close()
            load_geometry_dataset(h.name, name)
        except Exception as exc:
            state.geometry_error_message = str(exc)
            state.flush()
        finally:
            state.geometry_upload = None
            state.flush()


def build_geometry_drawer():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller
    with html.Div(v_show="active_tab === 1", classes="pa-4"):
        vuetify.VFileInput(
            label="Choose VTK dataset",
            v_model=("geometry_upload", None),
            accept=".vtk,.vtu,.vtp,.vti,.vtr,.vts,.ply,.stl,.obj",
            dense=True,
            hide_details=True,
            classes="mb-3",
        )
        html.Div("{{ geometry_file_name }}", classes="text-subtitle-1 font-weight-bold text-cyan-900")
        html.Div("{{ geometry_dataset_type }}", classes="text-caption text--secondary")
        html.Div("{{ geometry_dataset_info }}", classes="text-caption text--secondary mb-3")
        vuetify.VAlert(
            "{{ geometry_error_message }}",
            v_if="geometry_error_message",
            type="error",
            dense=True,
            outlined=True,
            classes="mb-3",
        )
        vuetify.VBtn(
            "Reset Camera",
            click=ctrl.reset_geometry_camera,
            block=True,
            classes="theme-btn-primary mt-4",
        )


def build_geometry_content():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-0",
        v_if="active_tab === 1",
    ):
        view = vtk_widgets.VtkRemoteLocalView(
            render_window,
            interactive_ratio=1,
            classes="fill-height w-100",
        )
        ctrl.geometry_view_update = view.update
        ctrl.geometry_view_reset_camera = view.reset_camera
