from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

import vtk
from trame.app import get_server

# Suppress native VTK pop-up error window on Windows
vtk_output = vtk.vtkFileOutputWindow()
vtk_output.SetFileName(os.devnull)
vtk.vtkOutputWindow.GetInstance().SetInstance(vtk_output)
from trame.ui.vuetify import SinglePageWithDrawerLayout
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

server = get_server(client_type="vue2")
server.cli.add_argument("--data", help="Optional dataset to load at startup")
state, ctrl = server.state, server.controller

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

transform = vtk.vtkTransform()
transform_filter = vtk.vtkTransformFilter()
transform_filter.SetTransform(transform)

plane = vtk.vtkPlane()
cutter = vtk.vtkCutter()
cutter.SetCutFunction(plane)
clipper = vtk.vtkClipDataSet()
clipper.SetClipFunction(plane)

surface_mapper = vtk.vtkDataSetMapper()
surface_actor = vtk.vtkActor()
surface_actor.SetMapper(surface_mapper)
surface_actor.GetProperty().SetColor(0.72, 0.78, 0.86)

result_mapper = vtk.vtkDataSetMapper()
result_actor = vtk.vtkActor()
result_actor.SetMapper(result_mapper)
result_actor.GetProperty().SetColor(0.12, 0.78, 0.95)
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

dataset = None
temp_file: str | None = None
data_arrays: dict[str, tuple[str, str, tuple[float, float]]] = {}


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


def _update_result() -> None:
    if dataset is None:
        return

    # Safe float parsing
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
        # Apply transform upstream to the whole dataset
        transform.Identity()
        transform.Translate(tx, ty, tz)
        transform.RotateX(rx)
        transform.RotateY(ry)
        transform.RotateZ(rz)
        transform.Scale(sx, sy, sz)
        transform_filter.SetInputData(dataset)
        transform_filter.Update()
        transformed_output = transform_filter.GetOutput()
        
        # Reset result actor transform
        result_actor.SetUserTransform(None)
    else:
        # Pass raw dataset to slice/clip pipeline
        transformed_output = dataset
        surface_mapper.SetInputData(dataset)
        cutter.SetInputData(dataset)
        clipper.SetInputData(dataset)
        outline.SetInputData(dataset)

        # Apply transform specifically to result_actor
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
    low, high = bounds[2 * axis_index : 2 * axis_index + 2]
    position = low + state.slice_fraction * (high - low)
    center = list(transformed_output.GetCenter())
    center[axis_index] = position

    plane.SetNormal(_normal_from_axis(axis))
    plane.SetOrigin(center)

    if state.operation == "Transform":
        surface_actor.SetVisibility(True)
        surface_actor.GetProperty().SetOpacity(1.0)
        result_actor.SetVisibility(False)
    elif state.operation == "Clip":
        clipper.SetInsideOut(bool(state.invert_clip))
        clipper.Update()
        result_mapper.SetInputConnection(clipper.GetOutputPort())
        surface_actor.SetVisibility(bool(state.show_context))
        surface_actor.GetProperty().SetOpacity(state.context_opacity)
        result_actor.SetVisibility(True)
        result_actor.GetProperty().SetRepresentationToSurface()
    else:
        cutter.Update()
        result_mapper.SetInputConnection(cutter.GetOutputPort())
        surface_actor.SetVisibility(bool(state.show_context))
        surface_actor.GetProperty().SetOpacity(state.context_opacity)
        result_actor.SetVisibility(True)
        result_actor.GetProperty().SetRepresentationToSurface()

    _set_mapper_coloring(surface_mapper, state.scalar)
    _set_mapper_coloring(result_mapper, state.scalar)
    result_mapper.Update()
    ctrl.view_update()


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

    # If content is still missing, check if item itself is a dict or string container
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
state.setdefault("context_opacity", 0.9)
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


with SinglePageWithDrawerLayout(server) as layout:
    layout.title.set_text("VTK Slicer")
    layout.icon.hide()

    with layout.toolbar:
        vuetify.VSpacer()
        vuetify.VBtn(
            "Reset camera",
            click=ctrl.reset_camera,
            icon="mdi-camera-retake-outline",
            text=True,
        )

    with layout.drawer:
        with vuetify.VContainer(classes="pa-4"):
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

            html.Div("OPERATION", classes="text-overline text--secondary")
            with vuetify.VBtnToggle(
                v_model=("operation", "Slice"),
                mandatory=True,
                dense=True,
                classes="w-100 mb-4",
            ):
                vuetify.VBtn("Slice", value="Slice", classes="flex-grow-1")
                vuetify.VBtn("Clip", value="Clip", classes="flex-grow-1")
                vuetify.VBtn("Transform", value="Transform", classes="flex-grow-1")

            # Slice / Clip controls (shown when operation is Slice or Clip)
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
                    v_model=("context_opacity", 0.9),
                    min=0,
                    max=1,
                    step=0.01,
                    v_if="show_context",
                    hide_details=True,
                    classes="mb-3",
                )

            # Transform controls (shown when operation is Transform)
            with html.Div(v_if="operation === 'Transform'"):
                vuetify.VSelect(
                    label="Transform Target",
                    v_model=("transform_target", "Entire Model"),
                    items=("['Entire Model', 'Slice / Clip Result Only']",),
                    dense=True,
                    hide_details=True,
                    classes="mb-3",
                )

                # Translation Sliders
                html.Div("Translate X", classes="text-caption font-weight-bold mt-2 mb-n2")
                vuetify.VSlider(v_model=("trans_x", 0.0), min=-50.0, max=50.0, step=0.1, dense=True, hide_details=True)
                html.Div("Translate Y", classes="text-caption font-weight-bold mt-2 mb-n2")
                vuetify.VSlider(v_model=("trans_y", 0.0), min=-50.0, max=50.0, step=0.1, dense=True, hide_details=True)
                html.Div("Translate Z", classes="text-caption font-weight-bold mt-2 mb-n2")
                vuetify.VSlider(v_model=("trans_z", 0.0), min=-50.0, max=50.0, step=0.1, dense=True, hide_details=True)

                # Rotation Sliders
                html.Div("Rotate X (°)", classes="text-caption font-weight-bold mt-3 mb-n2")
                vuetify.VSlider(v_model=("rot_x", 0.0), min=-180.0, max=180.0, step=1.0, dense=True, hide_details=True)
                html.Div("Rotate Y (°)", classes="text-caption font-weight-bold mt-2 mb-n2")
                vuetify.VSlider(v_model=("rot_y", 0.0), min=-180.0, max=180.0, step=1.0, dense=True, hide_details=True)
                html.Div("Rotate Z (°)", classes="text-caption font-weight-bold mt-2 mb-n2")
                vuetify.VSlider(v_model=("rot_z", 0.0), min=-180.0, max=180.0, step=1.0, dense=True, hide_details=True)

                # Scale Sliders
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

    with layout.content:
        with vuetify.VContainer(fluid=True, classes="fill-height pa-0"):
            view = vtk_widgets.VtkRemoteLocalView(
                render_window,
                interactive_ratio=1,
                classes="fill-height w-100",
            )
            ctrl.view_update = view.update
            ctrl.view_reset_camera = view.reset_camera


def main():
    args, _ = server.cli.parse_known_args()
    if args.data:
        try:
            load_dataset(args.data)
        except Exception as exc:
            state.error_message = str(exc)
    server.start(port=8087)


if __name__ == "__main__":
    main()
