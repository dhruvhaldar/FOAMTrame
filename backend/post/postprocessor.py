"""Post-processor module for FOAMTrame using Trame and VTK.

Provides full interactive post-processing capabilities (Slice, Clip, Transform, Streamlines)
from the trame_vtk_slicer project embedded seamlessly into FOAMTrame.
"""

from __future__ import annotations

import base64
import logging
import multiprocessing
import os
import socket
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional

import vtk

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


def _wait_for_port(host: str, port: int, timeout: float = 60.0) -> bool:
    """Probe host:port until it accepts connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.1)
    return False


class TrameVisualizer:
    """
    Handles interactive VTK visualization using Trame.
    Supports Slice, Clip, Transform, and Streamlines operations.
    """

    _process: Optional[multiprocessing.Process] = None
    _current_port: Optional[int] = None

    def __init__(self) -> None:
        pass

    def start_visualization(
        self,
        case_or_file_path: str,
        params: Optional[Dict[str, Any]] = None,
        host: str = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Starts a Trame process for interactive post-processing.

        Args:
            case_or_file_path: Path to case directory or a specific VTK/mesh file.
            params: Dict of initial parameters (e.g. initial operation 'Slice', 'Clip', etc.).
            host: Host bind address.
        """
        try:
            target_file = self._resolve_target_file(case_or_file_path)
            if not target_file:
                return {"status": "error", "message": "No suitable VTK or mesh file found"}

            if params is None:
                params = {}

            # Terminate existing process if active
            self.stop_visualization()

            port_queue: multiprocessing.Queue = multiprocessing.Queue()

            p = multiprocessing.Process(
                target=_run_trame_visualizer_process,
                args=(target_file, params, port_queue, host),
                daemon=True
            )
            p.start()
            TrameVisualizer._process = p

            try:
                result = port_queue.get(timeout=60)
            except Exception:
                p.terminate()
                return {"status": "error", "message": "Trame process timed out during startup"}

            if "error" in result:
                return {"status": "error", "message": result["error"]}

            port = result["port"]
            TrameVisualizer._current_port = port

            if not _wait_for_port(host, port, timeout=60.0):
                p.terminate()
                return {"status": "error", "message": "Trame server failed to start listening on port"}

            return {
                "status": "success",
                "mode": "iframe",
                "src": f"http://{host}:{port}/index.html",
                "port": port
            }

        except Exception as e:
            logger.error(f"[FOAMTrame] TrameVisualizer error: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def stop_visualization(self) -> None:
        """Stop running visualization process."""
        if TrameVisualizer._process:
            if TrameVisualizer._process.is_alive():
                logger.info(f"[FOAMTrame] Terminating Trame visualizer process {TrameVisualizer._process.pid}")
                TrameVisualizer._process.terminate()
                TrameVisualizer._process.join(timeout=2)
                if TrameVisualizer._process.is_alive():
                    TrameVisualizer._process.kill()
            TrameVisualizer._process = None
            TrameVisualizer._current_port = None

    def _resolve_target_file(self, path_str: str) -> Optional[str]:
        """Find a VTK/mesh file if a directory path is given, with robust path resolution and fallback."""
        if not path_str:
            path_str = ""

        path = Path(path_str)
        if path.is_file():
            return str(path)

        candidate_dirs = [
            path,
            Path(os.getcwd()) / path,
            Path(os.getcwd()) / "FOAM_RUN" / path,
            Path(os.getcwd()) / "tutorials" / path,
        ]

        vtk_files = []
        for cdir in candidate_dirs:
            if cdir.exists():
                for ext in ("*.vtk", "*.vtu", "*.vtp", "*.vti", "*.vtr", "*.vts", "*.ply", "*.stl", "*.obj"):
                    vtk_files.extend(cdir.rglob(ext))

        if vtk_files:
            return str(max(vtk_files, key=os.path.getmtime))

        # Fallback: if no VTK file was generated yet, create a default 3D sample mesh so visualizer never opens empty
        sample_path = Path(tempfile.gettempdir()) / "FOAMTrame_default_sample.vtk"
        try:
            sphere = vtk.vtkSphereSource()
            sphere.SetRadius(1.0)
            sphere.SetThetaResolution(32)
            sphere.SetPhiResolution(32)
            sphere.Update()
            writer = vtk.vtkPolyDataWriter()
            writer.SetFileName(str(sample_path))
            writer.SetInputData(sphere.GetOutput())
            writer.Write()
            return str(sample_path)
        except Exception:
            return None


def _run_trame_visualizer_process(
    initial_file: str,
    params: Dict[str, Any],
    port_queue: multiprocessing.Queue,
    host: str = "127.0.0.1"
) -> None:
    """
    Subprocess entry point running the full trame_vtk_slicer app engine.
    """
    try:
        # Pre-claim socket port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, 0))
            port = s.getsockname()[1]
        port_queue.put({"port": port})

        # Suppress VTK output window
        vtk_output = vtk.vtkFileOutputWindow()
        vtk_output.SetFileName(os.devnull)
        vtk.vtkOutputWindow.GetInstance().SetInstance(vtk_output)

        from trame.app import get_server
        from trame.ui.vuetify import SinglePageWithDrawerLayout
        from trame.widgets import html, vtk as vtk_widgets, vuetify

        server = get_server(client_type="vue2")
        assert server is not None
        state, ctrl = server.state, server.controller

        logger.info(f"[FOAMTrame Post] Starting Trame subprocess with initial_file='{initial_file}' on port {port}")

        # VTK setup
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
        interactor.Initialize()

        # Pipelines
        transform = vtk.vtkTransform()
        transform_filter = vtk.vtkTransformFilter()
        transform_filter.SetTransform(transform)

        plane = vtk.vtkPlane()
        cutter = vtk.vtkCutter()
        cutter.SetCutFunction(plane)
        clipper = vtk.vtkClipDataSet()
        clipper.SetClipFunction(plane)

        stream_seeds = vtk.vtkPointSource()
        stream_seeds.SetNumberOfPoints(200)
        stream_seeds.SetRadius(1.0)

        stream_tracer = vtk.vtkStreamTracer()
        stream_tracer.SetSourceConnection(stream_seeds.GetOutputPort())
        stream_tracer.SetMaximumPropagation(100.0)
        stream_tracer.SetInitialIntegrationStep(0.1)
        stream_tracer.SetMaximumIntegrationStep(1.0)
        stream_tracer.SetIntegrationDirectionToBoth()
        stream_tracer.SetIntegratorTypeToRungeKutta45()

        stream_tube = vtk.vtkTubeFilter()
        stream_tube.SetInputConnection(stream_tracer.GetOutputPort())
        stream_tube.SetRadius(0.02)
        stream_tube.SetNumberOfSides(8)
        stream_tube.SetVaryRadiusToVaryRadiusOff()

        stream_mapper = vtk.vtkPolyDataMapper()
        stream_mapper.SetInputConnection(stream_tube.GetOutputPort())

        stream_actor = vtk.vtkActor()
        stream_actor.SetMapper(stream_mapper)
        stream_actor.GetProperty().SetColor(1.0, 0.55, 0.0)
        stream_actor.SetVisibility(False)

        surface_mapper = vtk.vtkDataSetMapper()
        surface_actor = vtk.vtkActor()
        surface_actor.SetMapper(surface_mapper)
        surface_actor.GetProperty().SetColor(0.72, 0.78, 0.86)

        result_mapper = vtk.vtkDataSetMapper()
        result_actor = vtk.vtkActor()
        result_actor.SetMapper(result_mapper)
        result_actor.GetProperty().SetColor(0.06, 0.72, 0.84)
        result_actor.GetProperty().SetLineWidth(3)

        outline = vtk.vtkOutlineFilter()
        outline_mapper = vtk.vtkPolyDataMapper()
        outline_mapper.SetInputConnection(outline.GetOutputPort())
        outline_actor = vtk.vtkActor()
        outline_actor.SetMapper(outline_mapper)
        outline_actor.GetProperty().SetColor(0.38, 0.45, 0.55)
        outline_actor.GetProperty().SetOpacity(0.65)

        dummy_source = vtk.vtkSphereSource()
        dummy_source.Update()
        dummy_data = dummy_source.GetOutput()

        transform_filter.SetInputData(dummy_data)
        transform_filter.Update()

        surface_mapper.SetInputConnection(transform_filter.GetOutputPort())
        cutter.SetInputConnection(transform_filter.GetOutputPort())
        cutter.Update()
        result_mapper.SetInputConnection(cutter.GetOutputPort())
        clipper.SetInputConnection(transform_filter.GetOutputPort())
        outline.SetInputConnection(transform_filter.GetOutputPort())

        renderer.AddActor(surface_actor)
        renderer.AddActor(result_actor)
        renderer.AddActor(outline_actor)
        renderer.AddActor(stream_actor)

        local_dataset = [None]
        local_temp_file = [None]
        data_arrays: Dict[str, tuple[str, str, tuple[float, float]]] = {}
        vector_arrays: Dict[str, str] = {}

        def _reader_for(p: str):
            ext = Path(p).suffix.lower()
            r_cls = READERS.get(ext)
            if not r_cls:
                raise ValueError(f"Unsupported extension '{ext}'")
            return r_cls()

        def _array_catalog(data_obj):
            cat = {}
            for assoc, attr in (("Point", data_obj.GetPointData()), ("Cell", data_obj.GetCellData())):
                for idx in range(attr.GetNumberOfArrays()):
                    arr = attr.GetArray(idx)
                    name = arr.GetName() if arr else None
                    if not arr or not name or arr.GetNumberOfComponents() != 1:
                        continue
                    key = f"{assoc}: {name}"
                    cat[key] = (assoc, name, arr.GetRange())
            return cat

        def _vector_catalog(data_obj):
            cat = {}
            pd = data_obj.GetPointData()
            for idx in range(pd.GetNumberOfArrays()):
                arr = pd.GetArray(idx)
                if arr and arr.GetNumberOfComponents() == 3:
                    name = arr.GetName()
                    if name:
                        cat[f"Point: {name}"] = name
            return cat

        def _normal_from_axis(ax: str):
            return {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}.get(ax, (1.0, 0.0, 0.0))

        def _set_mapper_coloring(mapper, selection: str):
            if not selection or selection == "Solid colour" or selection not in data_arrays:
                mapper.ScalarVisibilityOff()
                return

            association, name, value_range = data_arrays[selection]
            mapper.ScalarVisibilityOn()
            mapper.SelectColorArray(name)
            mapper.SetScalarRange(*value_range)
            if association == "Point":
                mapper.SetScalarModeToUsePointFieldData()
            else:
                mapper.SetScalarModeToUseCellFieldData()

        def _update_result():
            ds = local_dataset[0]
            if ds is None:
                return

            try:
                tx, ty, tz = float(state.trans_x or 0), float(state.trans_y or 0), float(state.trans_z or 0)
                rx, ry, rz = float(state.rot_x or 0), float(state.rot_y or 0), float(state.rot_z or 0)
                sx, sy, sz = float(state.scale_x or 1), float(state.scale_y or 1), float(state.scale_z or 1)
            except (ValueError, TypeError):
                tx, ty, tz = 0.0, 0.0, 0.0
                rx, ry, rz = 0.0, 0.0, 0.0
                sx, sy, sz = 1.0, 1.0, 1.0

            target = state.transform_target or "Entire Model"

            if target == "Entire Model":
                transform.Identity()
                transform.Translate(tx, ty, tz)
                transform.RotateX(rx)
                transform.RotateY(ry)
                transform.RotateZ(rz)
                transform.Scale(sx, sy, sz)
                transform_filter.SetInputData(ds)
                transform_filter.Update()
                transformed_output = transform_filter.GetOutput()
                result_actor.SetUserTransform(None)
            else:
                transformed_output = ds
                surface_mapper.SetInputData(ds)
                cutter.SetInputData(ds)
                clipper.SetInputData(ds)
                outline.SetInputData(ds)

                user_tr = vtk.vtkTransform()
                user_tr.Translate(tx, ty, tz)
                user_tr.RotateX(rx)
                user_tr.RotateY(ry)
                user_tr.RotateZ(rz)
                user_tr.Scale(sx, sy, sz)
                result_actor.SetUserTransform(user_tr)

            bounds = transformed_output.GetBounds()
            axis = state.slice_axis or "X"
            axis_index = {"X": 0, "Y": 1, "Z": 2}[axis]
            low, high = bounds[2 * axis_index: 2 * axis_index + 2]
            position = low + float(state.slice_fraction or 0.5) * (high - low)
            center = list(transformed_output.GetCenter())
            center[axis_index] = position

            plane.SetNormal(_normal_from_axis(axis))
            plane.SetOrigin(center)

            operation = state.operation or "Slice"

            result_actor.SetVisibility(False)
            stream_actor.SetVisibility(False)
            surface_actor.SetVisibility(True)
            surface_actor.GetProperty().SetOpacity(1.0)

            if operation == "Transform":
                surface_mapper.SetInputData(transformed_output)
                surface_actor.SetVisibility(True)
                surface_actor.GetProperty().SetOpacity(1.0)

            elif operation == "Clip":
                surface_actor.SetVisibility(bool(state.show_context))
                surface_actor.GetProperty().SetOpacity(float(state.context_opacity or 0.45))
                surface_mapper.SetInputData(transformed_output)
                clipper.SetInputData(transformed_output)
                clipper.SetInsideOut(bool(state.invert_clip))
                clipper.Update()
                result_mapper.SetInputConnection(clipper.GetOutputPort())
                result_actor.SetVisibility(True)
                result_actor.GetProperty().SetRepresentationToSurface()

            elif operation == "Slice":
                surface_actor.SetVisibility(bool(state.show_context))
                surface_actor.GetProperty().SetOpacity(float(state.context_opacity or 0.45))
                surface_mapper.SetInputData(transformed_output)
                cutter.SetInputData(transformed_output)
                cutter.Update()
                result_mapper.SetInputConnection(cutter.GetOutputPort())
                result_actor.SetVisibility(True)
                result_actor.GetProperty().SetRepresentationToSurface()

            elif operation == "Streamlines":
                _update_streamlines(transformed_output)
                surface_actor.SetVisibility(bool(state.show_context))
                surface_actor.GetProperty().SetOpacity(float(state.context_opacity or 0.25))
                surface_mapper.SetInputData(transformed_output)

            outline.SetInputData(transformed_output)
            outline.Update()
            _set_mapper_coloring(surface_mapper, state.scalar)
            _set_mapper_coloring(result_mapper, state.scalar)
            surface_mapper.Update()
            result_mapper.Update()
            renderer.ResetCameraClippingRange()
            ctrl.view_update()

        def _update_streamlines(data_obj):
            vector_key = state.stream_vector or ""
            array_name = vector_arrays.get(vector_key, "")

            if not array_name:
                stream_actor.SetVisibility(False)
                return

            pd = data_obj.GetPointData()
            pd.SetActiveVectors(array_name)

            bounds = data_obj.GetBounds()
            cx = (bounds[0] + bounds[1]) * 0.5
            cy = (bounds[2] + bounds[3]) * 0.5
            cz = (bounds[4] + bounds[5]) * 0.5
            diag = (
                (bounds[1] - bounds[0]) ** 2
                + (bounds[3] - bounds[2]) ** 2
                + (bounds[5] - bounds[4]) ** 2
            ) ** 0.5

            seed_radius = float(state.stream_seed_radius or 0.33) * diag * 0.5

            stream_seeds.SetCenter(cx, cy, cz)
            stream_seeds.SetRadius(max(seed_radius, 1e-6))
            stream_seeds.SetNumberOfPoints(int(state.stream_num_seeds or 200))
            stream_seeds.Update()

            direction_map = {
                "Both": vtk.vtkStreamTracer.BOTH,
                "Forward": vtk.vtkStreamTracer.FORWARD,
                "Backward": vtk.vtkStreamTracer.BACKWARD,
            }
            direction = direction_map.get(state.stream_direction or "Both", vtk.vtkStreamTracer.BOTH)
            stream_tracer.SetIntegrationDirection(direction)
            stream_tracer.SetMaximumPropagation(float(state.stream_max_prop or 100.0))
            stream_tracer.SetInitialIntegrationStep(float(state.stream_step or 0.1))

            stream_tracer.SetInputData(data_obj)
            stream_tracer.Update()

            tube_radius = float(state.stream_tube_radius or 0.5) * diag * 0.005
            stream_tube.SetRadius(max(tube_radius, 1e-7))
            stream_tube.Update()

            speed_arr = stream_tracer.GetOutput().GetPointData().GetArray("Velocity")
            if speed_arr is None:
                speed_arr = stream_tracer.GetOutput().GetPointData().GetArray(array_name)

            if bool(state.stream_color_by_speed) and speed_arr is not None:
                stream_mapper.ScalarVisibilityOn()
                stream_mapper.SetScalarModeToUsePointFieldData()
                stream_mapper.SelectColorArray(speed_arr.GetName())
                stream_mapper.SetScalarRange(speed_arr.GetRange())
            else:
                stream_mapper.ScalarVisibilityOff()

            stream_actor.SetVisibility(True)

        def load_dataset(path: str, display_name: str | None = None):
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
            local_dataset[0] = ds
            transform_filter.SetInputData(ds)

            data_arrays.clear()
            data_arrays.update(_array_catalog(ds))
            state.scalar_items = ["Solid colour", *data_arrays.keys()]
            state.scalar = next(iter(data_arrays), "Solid colour")

            vector_arrays.clear()
            vector_arrays.update(_vector_catalog(ds))
            vec_keys = list(vector_arrays.keys())
            state.stream_vector_items = vec_keys if vec_keys else ["(no vector arrays)"]
            state.stream_vector = vec_keys[0] if vec_keys else ""

            state.file_name = display_name or Path(path).name
            state.dataset_type = ds.GetClassName().replace("vtk", "")
            state.dataset_info = f"{ds.GetNumberOfPoints():,} pts · {ds.GetNumberOfCells():,} cells"
            state.error_message = ""
            state.slice_fraction = 0.5

            _update_result()
            renderer.ResetCamera()
            renderer.ResetCameraClippingRange()
            render_window.Render()
            ctrl.view_update()

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

        @state.change("upload")
        def on_upload(upload, **_):
            if not upload:
                return
            try:
                name, content = _uploaded_bytes(upload)
                ext = Path(name).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    raise ValueError(f"Unsupported file type '{ext}'")
                if local_temp_file[0] and os.path.exists(local_temp_file[0]):
                    os.unlink(local_temp_file[0])
                h = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                h.write(content)
                h.close()
                local_temp_file[0] = h.name
                load_dataset(local_temp_file[0], name)
            except Exception as exc:
                state.error_message = str(exc)
            finally:
                state.upload = None

        @state.change(
            "slice_axis",
            "slice_fraction",
            "operation",
            "invert_clip",
            "show_context",
            "context_opacity",
            "scalar",
            "transform_target",
            "trans_x",
            "trans_y",
            "trans_z",
            "rot_x",
            "rot_y",
            "rot_z",
            "scale_x",
            "scale_y",
            "scale_z",
            "stream_vector",
            "stream_num_seeds",
            "stream_seed_radius",
            "stream_max_prop",
            "stream_step",
            "stream_direction",
            "stream_tube_radius",
            "stream_color_by_speed",
        )
        def on_controls_changed(**_):
            _update_result()

        def reset_transform():
            state.trans_x = 0.0
            state.trans_y = 0.0
            state.trans_z = 0.0
            state.rot_x = 0.0
            state.rot_y = 0.0
            state.rot_z = 0.0
            state.scale_x = 1.0
            state.scale_y = 1.0
            state.scale_z = 1.0
            _update_result()

        def reset_camera():
            renderer.ResetCamera()
            renderer.ResetCameraClippingRange()
            ctrl.view_update()

        ctrl.reset_camera = reset_camera
        ctrl.reset_transform = reset_transform

        # State defaults
        state.setdefault("upload", None)
        state["viewMode"] = "local"
        state.setdefault("file_name", "No dataset loaded")
        state.setdefault("dataset_type", "—")
        state.setdefault("dataset_info", "Upload a dataset to begin")
        state.setdefault("error_message", "")
        state.setdefault("operation", params.get("operation", "Slice"))
        state.setdefault("slice_axis", "X")
        state.setdefault("slice_fraction", 0.5)
        state.setdefault("invert_clip", False)
        state.setdefault("show_context", True)
        state.setdefault("context_opacity", 0.45)
        state.setdefault("scalar", "Solid colour")
        state.setdefault("scalar_items", ["Solid colour"])
        state.setdefault("transform_target", "Entire Model")
        state.setdefault("trans_x", 0.0)
        state.setdefault("trans_y", 0.0)
        state.setdefault("trans_z", 0.0)
        state.setdefault("rot_x", 0.0)
        state.setdefault("rot_y", 0.0)
        state.setdefault("rot_z", 0.0)
        state.setdefault("scale_x", 1.0)
        state.setdefault("scale_y", 1.0)
        state.setdefault("scale_z", 1.0)
        state.setdefault("stream_vector", "")
        state.setdefault("stream_vector_items", ["(no vector arrays)"])
        state.setdefault("stream_num_seeds", 200)
        state.setdefault("stream_seed_radius", 0.33)
        state.setdefault("stream_max_prop", 100.0)
        state.setdefault("stream_step", 0.1)
        state.setdefault("stream_direction", "Both")
        state.setdefault("stream_tube_radius", 0.5)
        state.setdefault("stream_color_by_speed", True)

        # Build UI layout
        with SinglePageWithDrawerLayout(server) as layout:
            layout.title.set_text("FOAMTrame PostProcessor")
            layout.icon.hide()

            with layout.toolbar:
                vuetify.VSpacer()
                vuetify.VBtn(
                    "Reset Camera",
                    click=ctrl.reset_camera,
                    icon="mdi-camera-retake-outline",
                    text=True,
                )

            with layout.drawer:
                with vuetify.VContainer(classes="pa-4"):
                    vuetify.VFileInput(
                        label="Choose VTK / Mesh File",
                        v_model=("upload", None),
                        accept=".vtk,.vtu,.vtp,.vti,.vtr,.vts,.ply,.stl,.obj",
                        dense=True,
                        hide_details=True,
                        classes="mb-3",
                    )
                    html.Div("{{ file_name }}", classes="text-subtitle-1 font-weight-bold text-cyan-900")
                    html.Div("{{ dataset_type }}", classes="text-caption text--secondary")
                    html.Div("{{ dataset_info }}", classes="text-caption text--secondary mb-3")
                    vuetify.VAlert(
                        "{{ error_message }}",
                        v_if="error_message",
                        type="error",
                        dense=True,
                        outlined=True,
                        classes="mb-3",
                    )
                    vuetify.VDivider(classes="my-3")

                    html.Div("OPERATION", classes="text-overline text--secondary mb-1")
                    with html.Div(classes="mb-4"):
                        vuetify.VBtn(
                            "Slice",
                            click="operation = 'Slice'",
                            color=("operation === 'Slice' ? 'primary' : ''",),
                            block=True,
                            dense=True,
                            outlined=("operation !== 'Slice'",),
                            classes="mb-1 justify-start",
                        )
                        vuetify.VBtn(
                            "Clip",
                            click="operation = 'Clip'",
                            color=("operation === 'Clip' ? 'primary' : ''",),
                            block=True,
                            dense=True,
                            outlined=("operation !== 'Clip'",),
                            classes="mb-1 justify-start",
                        )
                        vuetify.VBtn(
                            "Transform",
                            click="operation = 'Transform'",
                            color=("operation === 'Transform' ? 'primary' : ''",),
                            block=True,
                            dense=True,
                            outlined=("operation !== 'Transform'",),
                            classes="mb-1 justify-start",
                        )
                        vuetify.VBtn(
                            "Streamlines",
                            click="operation = 'Streamlines'",
                            color=("operation === 'Streamlines' ? 'primary' : ''",),
                            block=True,
                            dense=True,
                            outlined=("operation !== 'Streamlines'",),
                            classes="mb-1 justify-start",
                        )

                    # --- Slice / Clip controls ---
                    with html.Div(v_if="operation === 'Slice' || operation === 'Clip'"):
                        vuetify.VSelect(
                            label="Plane axis",
                            v_model=("slice_axis", "X"),
                            items=("['X', 'Y', 'Z']",),
                            dense=True,
                            hide_details=True,
                            classes="mb-3",
                        )
                        html.Div(
                            "Position {{ Math.round(slice_fraction * 100) }}%",
                            classes="text-caption mb-n2",
                        )
                        vuetify.VSlider(
                            v_model=("slice_fraction", 0.5),
                            min=0,
                            max=1,
                            step=0.001,
                            color="cyan",
                            hide_details=True,
                            classes="mb-3",
                        )
                        vuetify.VCheckbox(
                            label="Invert clipped side",
                            v_model=("invert_clip", False),
                            v_if="operation === 'Clip'",
                            dense=True,
                            hide_details=True,
                        )
                        vuetify.VCheckbox(
                            label="Show source as context",
                            v_model=("show_context", True),
                            dense=True,
                            hide_details=True,
                        )
                        vuetify.VSlider(
                            label="Context opacity",
                            v_model=("context_opacity", 0.45),
                            min=0,
                            max=1,
                            step=0.01,
                            v_if="show_context",
                            hide_details=True,
                            classes="mb-3",
                        )
                        vuetify.VSelect(
                            label="Colour by",
                            v_model=("scalar", "Solid colour"),
                            items=("scalar_items",),
                            dense=True,
                            hide_details=True,
                            classes="mb-3",
                        )

                    # --- Transform controls ---
                    with html.Div(v_if="operation === 'Transform'"):
                        vuetify.VSelect(
                            label="Transform Target",
                            v_model=("transform_target", "Entire Model"),
                            items=("['Entire Model', 'Slice / Clip Result Only']",),
                            dense=True,
                            hide_details=True,
                            classes="mb-3",
                        )

                        html.Div("Translate X", classes="text-caption font-weight-bold mt-2 mb-n2")
                        vuetify.VSlider(v_model=("trans_x", 0.0), min=-50.0, max=50.0, step=0.1, dense=True, hide_details=True)
                        html.Div("Translate Y", classes="text-caption font-weight-bold mt-2 mb-n2")
                        vuetify.VSlider(v_model=("trans_y", 0.0), min=-50.0, max=50.0, step=0.1, dense=True, hide_details=True)
                        html.Div("Translate Z", classes="text-caption font-weight-bold mt-2 mb-n2")
                        vuetify.VSlider(v_model=("trans_z", 0.0), min=-50.0, max=50.0, step=0.1, dense=True, hide_details=True)

                        html.Div("Rotate X (°)", classes="text-caption font-weight-bold mt-3 mb-n2")
                        vuetify.VSlider(v_model=("rot_x", 0.0), min=-180.0, max=180.0, step=1.0, dense=True, hide_details=True)
                        html.Div("Rotate Y (°)", classes="text-caption font-weight-bold mt-2 mb-n2")
                        vuetify.VSlider(v_model=("rot_y", 0.0), min=-180.0, max=180.0, step=1.0, dense=True, hide_details=True)
                        html.Div("Rotate Z (°)", classes="text-caption font-weight-bold mt-2 mb-n2")
                        vuetify.VSlider(v_model=("rot_z", 0.0), min=-180.0, max=180.0, step=1.0, dense=True, hide_details=True)

                        html.Div("Scale X", classes="text-caption font-weight-bold mt-3 mb-n2")
                        vuetify.VSlider(v_model=("scale_x", 1.0), min=0.1, max=5.0, step=0.05, dense=True, hide_details=True)
                        html.Div("Scale Y", classes="text-caption font-weight-bold mt-2 mb-n2")
                        vuetify.VSlider(v_model=("scale_y", 1.0), min=0.1, max=5.0, step=0.05, dense=True, hide_details=True)
                        html.Div("Scale Z", classes="text-caption font-weight-bold mt-2 mb-n2")
                        vuetify.VSlider(v_model=("scale_z", 1.0), min=0.1, max=5.0, step=0.05, dense=True, hide_details=True)

                        vuetify.VBtn(
                            "Reset Transform",
                            click=ctrl.reset_transform,
                            color="warning",
                            outlined=True,
                            small=True,
                            classes="w-100 mt-3",
                        )

                    # --- Streamlines controls ---
                    with html.Div(v_if="operation === 'Streamlines'"):
                        vuetify.VSelect(
                            label="Vector array",
                            v_model=("stream_vector", ""),
                            items=("stream_vector_items",),
                            dense=True,
                            hide_details=True,
                            classes="mb-3",
                        )
                        vuetify.VSelect(
                            label="Integration direction",
                            v_model=("stream_direction", "Both"),
                            items=("['Both', 'Forward', 'Backward']",),
                            dense=True,
                            hide_details=True,
                            classes="mb-3",
                        )
                        html.Div(
                            "Seeds: {{ stream_num_seeds }}",
                            classes="text-caption font-weight-bold mt-2 mb-n2",
                        )
                        vuetify.VSlider(
                            v_model=("stream_num_seeds", 200),
                            min=10,
                            max=1000,
                            step=10,
                            color="orange",
                            dense=True,
                            hide_details=True,
                        )
                        html.Div(
                            "Seed radius: {{ Math.round(stream_seed_radius * 100) }}% of bounds",
                            classes="text-caption font-weight-bold mt-2 mb-n2",
                        )
                        vuetify.VSlider(
                            v_model=("stream_seed_radius", 0.33),
                            min=0.01,
                            max=1.0,
                            step=0.01,
                            color="orange",
                            dense=True,
                            hide_details=True,
                        )
                        html.Div(
                            "Max propagation: {{ stream_max_prop }}",
                            classes="text-caption font-weight-bold mt-2 mb-n2",
                        )
                        vuetify.VSlider(
                            v_model=("stream_max_prop", 100.0),
                            min=1.0,
                            max=500.0,
                            step=1.0,
                            color="orange",
                            dense=True,
                            hide_details=True,
                        )
                        html.Div(
                            "Integration step: {{ stream_step }}",
                            classes="text-caption font-weight-bold mt-2 mb-n2",
                        )
                        vuetify.VSlider(
                            v_model=("stream_step", 0.1),
                            min=0.01,
                            max=1.0,
                            step=0.01,
                            color="orange",
                            dense=True,
                            hide_details=True,
                        )
                        html.Div(
                            "Tube radius: {{ stream_tube_radius }}",
                            classes="text-caption font-weight-bold mt-2 mb-n2",
                        )
                        vuetify.VSlider(
                            v_model=("stream_tube_radius", 0.5),
                            min=0.01,
                            max=5.0,
                            step=0.01,
                            color="orange",
                            dense=True,
                            hide_details=True,
                        )
                        html.Div(
                            "Context opacity: {{ Math.round(context_opacity * 100) }}%",
                            classes="text-caption font-weight-bold mt-2 mb-n2",
                        )
                        vuetify.VSlider(
                            v_model=("context_opacity", 0.25),
                            min=0.0,
                            max=1.0,
                            step=0.01,
                            color="orange",
                            dense=True,
                            hide_details=True,
                            classes="mb-2",
                        )
                        vuetify.VCheckbox(
                            label="Colour by speed",
                            v_model=("stream_color_by_speed", True),
                            dense=True,
                            hide_details=True,
                        )
                        vuetify.VCheckbox(
                            label="Show context mesh",
                            v_model=("show_context", True),
                            dense=True,
                            hide_details=True,
                        )

        with layout.content:
            with vuetify.VContainer(fluid=True, classes="fill-height pa-0"):
                view = vtk_widgets.VtkRemoteLocalView(
                    render_window,
                    namespace="view",
                    ref="view",
                    mode=("viewMode", "local"),
                    classes="fill-height w-100",
                )
                ctrl.view_update = view.update
                ctrl.view_reset_camera = view.reset_camera

        # Initial dataset load
        if initial_file and os.path.exists(initial_file):
            try:
                logger.info(f"[FOAMTrame Post] Loading initial dataset: {initial_file}")
                load_dataset(initial_file)
                render_window.Render()
                ctrl.view_update()
                logger.info(f"[FOAMTrame Post] Initial dataset loaded successfully: {state.file_name}, {state.dataset_info}")
            except Exception as exc:
                logger.error(f"[FOAMTrame Post] Initial dataset loading error: {exc}", exc_info=True)
                state.error_message = str(exc)
        else:
            logger.warning(f"[FOAMTrame Post] Initial file does not exist or not provided: {initial_file}")

        @ctrl.add("on_server_ready")
        def _on_ready(**_):
            renderer.ResetCamera()
            render_window.Render()
            ctrl.view_update()

        @ctrl.add("on_client_connected")
        def _on_client_connect(**_):
            renderer.ResetCamera()
            render_window.Render()
            ctrl.view_update()

        # Start server
        server.start(
            port=port,
            host=host,
            open_browser=False,
            disable_logging=True,
        )

    except Exception as e:
        try:
            port_queue.put({"error": str(e)})
        except Exception:
            pass
