from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

import vtk
from trame.widgets import html, vtk as vtk_widgets, vuetify


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

# --- Transform pipeline ---
transform = vtk.vtkTransform()
transform_filter = vtk.vtkTransformFilter()
transform_filter.SetTransform(transform)

# --- Slice / Clip pipeline ---
plane = vtk.vtkPlane()
sphere = vtk.vtkSphere()
box = vtk.vtkBox()
cutter = vtk.vtkCutter()
cutter.SetCutFunction(plane)
clipper = vtk.vtkClipDataSet()
clipper.SetClipFunction(plane)

# --- Streamlines pipeline ---
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

# --- Surface / context actor ---
surface_mapper = vtk.vtkDataSetMapper()
surface_actor = vtk.vtkActor()
surface_actor.SetMapper(surface_mapper)
surface_actor.GetProperty().SetColor(0.72, 0.78, 0.86)

# --- Slice / Clip result actor ---
result_mapper = vtk.vtkDataSetMapper()
result_actor = vtk.vtkActor()
result_actor.SetMapper(result_mapper)
result_actor.GetProperty().SetColor(0.12, 0.78, 0.95)
result_actor.GetProperty().SetLineWidth(3)

# --- Outline ---
outline = vtk.vtkOutlineFilter()
outline_mapper = vtk.vtkPolyDataMapper()
outline_mapper.SetInputConnection(outline.GetOutputPort())
outline_actor = vtk.vtkActor()
outline_actor.SetMapper(outline_mapper)
outline_actor.GetProperty().SetColor(0.38, 0.45, 0.55)
outline_actor.GetProperty().SetOpacity(0.65)

# Initialise pipeline with a dummy sphere so VTK does not complain at startup
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

dataset = None
temp_file: str | None = None
data_arrays: dict[str, tuple[str, str, tuple[float, float]]] = {}
vector_arrays: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reader_for(path: str):
    extension = Path(path).suffix.lower()
    reader_type = READERS.get(extension)
    if reader_type is None:
        raise ValueError(
            f"Unsupported file type '{extension}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return reader_type()


def _array_catalog(data_object) -> dict[str, tuple[str, str, tuple[float, float]]]:
    catalog = {}
    for association, attributes in (
        ("Point", data_object.GetPointData()),
        ("Cell", data_object.GetCellData()),
    ):
        for index in range(attributes.GetNumberOfArrays()):
            array = attributes.GetArray(index)
            name = array.GetName() if array else None
            if not array or not name or array.GetNumberOfComponents() != 1:
                continue
            key = f"{association}: {name}"
            catalog[key] = (association, name, array.GetRange())
    return catalog


def _vector_catalog(data_object) -> dict[str, str]:
    catalog = {}
    pd = data_object.GetPointData()
    for index in range(pd.GetNumberOfArrays()):
        array = pd.GetArray(index)
        if array and array.GetNumberOfComponents() == 3:
            name = array.GetName()
            if name:
                catalog[f"Point: {name}"] = name
    return catalog


def _normal_from_axis(axis: str) -> tuple[float, float, float]:
    return {
        "X": (1.0, 0.0, 0.0),
        "Y": (0.0, 1.0, 0.0),
        "Z": (0.0, 0.0, 1.0),
    }.get(axis, (1.0, 0.0, 0.0))


def _set_mapper_coloring(mapper, selection: str) -> None:
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


# ---------------------------------------------------------------------------
# Visualizer Tab Setup
# ---------------------------------------------------------------------------

def setup_visualizer_tab(server):
    state, ctrl = server.state, server.controller

    def _update_result() -> None:
        if dataset is None:
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
            transform_filter.SetInputData(dataset)
            transform_filter.Update()
            transformed_output = transform_filter.GetOutput()
            result_actor.SetUserTransform(None)
        else:
            transformed_output = dataset
            surface_mapper.SetInputData(dataset)
            cutter.SetInputData(dataset)
            clipper.SetInputData(dataset)
            outline.SetInputData(dataset)

            user_tr = vtk.vtkTransform()
            user_tr.Translate(tx, ty, tz)
            user_tr.RotateX(rx)
            user_tr.RotateY(ry)
            user_tr.RotateZ(rz)
            user_tr.Scale(sx, sy, sz)
            result_actor.SetUserTransform(user_tr)

        bounds = transformed_output.GetBounds()
        axis = state.slice_axis
        axis_index = {"X": 0, "Y": 1, "Z": 2}[axis]
        low, high = bounds[2 * axis_index: 2 * axis_index + 2]
        position = low + state.slice_fraction * (high - low)
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
            clip_type = state.clip_type or "Plane"

            if clip_type == "Plane":
                plane.SetNormal(_normal_from_axis(axis))
                plane.SetOrigin(center)
                clipper.SetClipFunction(plane)

            elif clip_type == "Sphere":
                bx = bounds[1] - bounds[0]
                by = bounds[3] - bounds[2]
                bz = bounds[5] - bounds[4]
                diag = (bx**2 + by**2 + bz**2) ** 0.5

                cx = bounds[0] + float(state.clip_sphere_cx or 0.5) * bx
                cy = bounds[2] + float(state.clip_sphere_cy or 0.5) * by
                cz = bounds[4] + float(state.clip_sphere_cz or 0.5) * bz
                radius = float(state.clip_sphere_radius or 0.3) * (diag * 0.5)

                sphere.SetCenter(cx, cy, cz)
                sphere.SetRadius(max(radius, 1e-6))
                clipper.SetClipFunction(sphere)

            elif clip_type == "Box":
                bx = bounds[1] - bounds[0]
                by = bounds[3] - bounds[2]
                bz = bounds[5] - bounds[4]
                eps = 1e-4

                f_xmin = float(state.clip_box_xmin if state.clip_box_xmin is not None else 0.0)
                f_xmax = float(state.clip_box_xmax if state.clip_box_xmax is not None else 1.0)
                f_ymin = float(state.clip_box_ymin if state.clip_box_ymin is not None else 0.0)
                f_ymax = float(state.clip_box_ymax if state.clip_box_ymax is not None else 1.0)
                f_zmin = float(state.clip_box_zmin if state.clip_box_zmin is not None else 0.0)
                f_zmax = float(state.clip_box_zmax if state.clip_box_zmax is not None else 1.0)

                xmin = bounds[0] + f_xmin * bx - (eps * bx if f_xmin == 0.0 else 0.0)
                xmax = bounds[0] + f_xmax * bx + (eps * bx if f_xmax == 1.0 else 0.0)
                ymin = bounds[2] + f_ymin * by - (eps * by if f_ymin == 0.0 else 0.0)
                ymax = bounds[2] + f_ymax * by + (eps * by if f_ymax == 1.0 else 0.0)
                zmin = bounds[4] + f_zmin * bz - (eps * bz if f_zmin == 0.0 else 0.0)
                zmax = bounds[4] + f_zmax * bz + (eps * bz if f_zmax == 1.0 else 0.0)

                if xmin >= xmax:
                    xmax = xmin + 1e-6
                if ymin >= ymax:
                    ymax = ymin + 1e-6
                if zmin >= zmax:
                    zmax = zmin + 1e-6

                box.SetBounds(xmin, xmax, ymin, ymax, zmin, zmax)
                clipper.SetClipFunction(box)

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

        _set_mapper_coloring(surface_mapper, state.scalar)
        _set_mapper_coloring(result_mapper, state.scalar)
        result_mapper.Update()
        ctrl.view_update()

    def _update_streamlines(data) -> None:
        vector_key = state.stream_vector or ""
        array_name = vector_arrays.get(vector_key, "")

        if not array_name:
            stream_actor.SetVisibility(False)
            return

        pd = data.GetPointData()
        pd.SetActiveVectors(array_name)

        bounds = data.GetBounds()
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

        stream_tracer.SetInputData(data)
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

    def load_dataset(path: str, display_name: str | None = None) -> None:
        global dataset

        reader = _reader_for(path)
        reader.SetFileName(path)
        reader.Update()
        output = reader.GetOutputDataObject(0)
        if output is None or not output.IsA("vtkDataSet"):
            raise ValueError("The file did not contain a VTK surface or volume dataset.")
        if output.GetNumberOfPoints() == 0:
            raise ValueError("The dataset contains no points.")

        dataset = output.NewInstance()
        dataset.ShallowCopy(output)
        transform_filter.SetInputData(dataset)

        data_arrays.clear()
        data_arrays.update(_array_catalog(dataset))
        state.scalar_items = ["Solid colour", *data_arrays.keys()]
        state.scalar = next(iter(data_arrays), "Solid colour")

        vector_arrays.clear()
        vector_arrays.update(_vector_catalog(dataset))
        vec_keys = list(vector_arrays.keys())
        state.stream_vector_items = vec_keys if vec_keys else ["(no vector arrays)"]
        state.stream_vector = vec_keys[0] if vec_keys else ""

        state.file_name = display_name or Path(path).name
        state.dataset_type = dataset.GetClassName().replace("vtk", "")
        state.dataset_info = (
            f"{dataset.GetNumberOfPoints():,} points · "
            f"{dataset.GetNumberOfCells():,} cells"
        )
        state.error_message = ""
        state.slice_fraction = 0.5

        _update_result()
        renderer.ResetCamera()
        renderer.ResetCameraClippingRange()
        ctrl.view_update()

    def _uploaded_bytes(file_value) -> tuple[str, bytes]:
        item = file_value
        if isinstance(file_value, (list, tuple)) and len(file_value) > 0:
            item = file_value[0]

        name = "dataset.vtk"
        content = None

        if isinstance(item, dict):
            name = item.get("name") or item.get("filename") or name
            content = item.get("content")
        elif hasattr(item, "name") or hasattr(item, "content") or hasattr(item, "filename"):
            name = getattr(item, "name", None) or getattr(item, "filename", None) or name
            content = getattr(item, "content", None)
        elif isinstance(item, (bytes, str)):
            content = item

        if content is None and isinstance(file_value, dict):
            name = file_value.get("name") or file_value.get("filename") or name
            content = file_value.get("content")

        if content is None:
            raise ValueError(f"Invalid upload payload: {file_value}")

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

        raise ValueError("Unsupported upload content encoding.")

    @state.change("upload")
    def on_upload(upload, **_):
        global temp_file
        if not upload:
            return
        try:
            name, content = _uploaded_bytes(upload)
            extension = Path(name).suffix.lower()
            if extension not in SUPPORTED_EXTENSIONS:
                raise ValueError(
                    f"Unsupported file type '{extension or '(none)'}'. "
                    f"Choose one of: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                )
            if temp_file and os.path.exists(temp_file):
                os.unlink(temp_file)
            handle = tempfile.NamedTemporaryFile(suffix=extension, delete=False)
            handle.write(content)
            handle.close()
            temp_file = handle.name
            load_dataset(temp_file, name)
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
        "clip_type",
        "clip_sphere_cx",
        "clip_sphere_cy",
        "clip_sphere_cz",
        "clip_sphere_radius",
        "clip_box_xmin",
        "clip_box_xmax",
        "clip_box_ymin",
        "clip_box_ymax",
        "clip_box_zmin",
        "clip_box_zmax",
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

    state.setdefault("upload", None)
    state.setdefault("file_name", "No dataset loaded")
    state.setdefault("dataset_type", "—")
    state.setdefault("dataset_info", "Upload a VTK dataset to begin")
    state.setdefault("error_message", "")
    state.setdefault("operation", "Slice")
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
    state.setdefault("clip_type", "Plane")
    state.setdefault("clip_type_items", ["Plane", "Sphere", "Box"])
    state.setdefault("clip_sphere_cx", 0.5)
    state.setdefault("clip_sphere_cy", 0.5)
    state.setdefault("clip_sphere_cz", 0.5)
    state.setdefault("clip_sphere_radius", 0.3)
    state.setdefault("clip_box_xmin", 0.0)
    state.setdefault("clip_box_xmax", 1.0)
    state.setdefault("clip_box_ymin", 0.0)
    state.setdefault("clip_box_ymax", 1.0)
    state.setdefault("clip_box_zmin", 0.0)
    state.setdefault("clip_box_zmax", 1.0)

    return load_dataset


# ---------------------------------------------------------------------------
# Visualizer Tab UI
# ---------------------------------------------------------------------------

def build_visualizer_drawer(ctrl):
    with vuetify.VContainer(classes="pa-4", v_show="active_tab === 4 || active_tab === 5"):
        vuetify.VFileInput(
            label="Choose VTK dataset",
            v_model=("upload", None),
            accept=".vtk,.vtu,.vtp,.vti,.vtr,.vts,.ply,.stl,.obj",
            dense=True,
            hide_details=True,
            classes="mb-3",
        )
        html.Div("{{ file_name }}", classes="text-subtitle-1 font-weight-bold")
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

        # --- Operation selector ---
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
                label="Clip shape",
                v_model=("clip_type", "Plane"),
                items=("clip_type_items",),
                v_if="operation === 'Clip'",
                dense=True,
                hide_details=True,
                classes="mb-3",
            )

            # Plane controls (Slice operation or Plane Clip)
            with html.Div(v_if="operation === 'Slice' || clip_type === 'Plane'"):
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

            # Sphere Clip controls
            with html.Div(v_if="operation === 'Clip' && clip_type === 'Sphere'"):
                html.Div(
                    "Radius: {{ Math.round(clip_sphere_radius * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_sphere_radius", 0.3),
                    min=0.01,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                    classes="mb-2",
                )
                html.Div(
                    "Center X: {{ Math.round(clip_sphere_cx * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_sphere_cx", 0.5),
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                    classes="mb-2",
                )
                html.Div(
                    "Center Y: {{ Math.round(clip_sphere_cy * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_sphere_cy", 0.5),
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                    classes="mb-2",
                )
                html.Div(
                    "Center Z: {{ Math.round(clip_sphere_cz * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_sphere_cz", 0.5),
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                    classes="mb-3",
                )

            # Box Clip controls
            with html.Div(v_if="operation === 'Clip' && clip_type === 'Box'"):
                html.Div(
                    "X Min: {{ Math.round(clip_box_xmin * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_box_xmin", 0.0),
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                )
                html.Div(
                    "X Max: {{ Math.round(clip_box_xmax * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_box_xmax", 1.0),
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                    classes="mb-2",
                )
                html.Div(
                    "Y Min: {{ Math.round(clip_box_ymin * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_box_ymin", 0.0),
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                )
                html.Div(
                    "Y Max: {{ Math.round(clip_box_ymax * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_box_ymax", 1.0),
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                    classes="mb-2",
                )
                html.Div(
                    "Z Min: {{ Math.round(clip_box_zmin * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_box_zmin", 0.0),
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    color="cyan",
                    hide_details=True,
                )
                html.Div(
                    "Z Max: {{ Math.round(clip_box_zmax * 100) }}%",
                    classes="text-caption font-weight-bold mt-1 mb-n2",
                )
                vuetify.VSlider(
                    v_model=("clip_box_zmax", 1.0),
                    min=0.0,
                    max=1.0,
                    step=0.01,
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


def build_visualizer_content(ctrl):
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-0",
        v_show="active_tab === 4 || active_tab === 5",
    ):
        view = vtk_widgets.VtkRemoteLocalView(
            render_window,
            interactive_ratio=1,
            classes="fill-height w-100",
        )
        ctrl.view_update = view.update
        ctrl.view_reset_camera = view.reset_camera
