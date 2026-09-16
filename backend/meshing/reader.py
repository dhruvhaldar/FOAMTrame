"""Read mesh geometry without interpreting OpenFOAM solution dictionaries."""

from pathlib import Path

import vtk


def read_mesh_patches(
    case_path: Path, patches: list[str] | None = None
) -> dict[str, vtk.vtkPolyData]:
    # A new reader also avoids reusing cached geometry after regeneration.
    reader = vtk.vtkOpenFOAMReader()
    reader.SetFileName(str(case_path / "FOAMTrame.foam"))
    # VTK also inspects an initial field while discovering metadata. Skipping
    # time zero prevents that path from parsing unexpanded tutorial macros.
    reader.SkipZeroTimeOn()
    reader.DisableAllCellArrays()
    reader.DisableAllPointArrays()
    reader.DisableAllLagrangianArrays()
    errors: list[str] = []

    @vtk.calldata_type(vtk.VTK_STRING)
    def record_error(_source, _event, message):
        errors.append(message or "OpenFOAM mesh could not be read")

    reader.AddObserver(vtk.vtkCommand.ErrorEvent, record_error)
    reader.UpdateInformation()
    # Array names are discovered during UpdateInformation, so disable fields
    # afterwards. Mesh inspection must not parse 0/U, 0/T, or other fields that
    # can contain OpenFOAM macros unsupported by VTK.
    reader.DisableAllCellArrays()
    reader.DisableAllPointArrays()
    reader.DisableAllLagrangianArrays()
    reader.DisableAllPatchArrays()
    for index in range(reader.GetNumberOfPatchArrays()):
        name = reader.GetPatchArrayName(index)
        # internalMesh exposes the exterior again even when a patch is hidden.
        if name != "internalMesh" and (
            patches is None or name.removeprefix("patch/") in patches
        ):
            reader.SetPatchArrayStatus(name, 1)
    reader.Update()
    if errors:
        raise ValueError(errors[0].strip())
    result: dict[str, vtk.vtkPolyData] = {}
    iterator = reader.GetOutput().NewIterator()
    iterator.InitTraversal()
    while not iterator.IsDoneWithTraversal():
        dataset = iterator.GetCurrentDataObject()
        metadata = iterator.GetCurrentMetaData()
        name = metadata.Get(vtk.vtkCompositeDataSet.NAME()) if metadata else None
        if name and isinstance(dataset, vtk.vtkPolyData):
            copied = vtk.vtkPolyData()
            copied.ShallowCopy(dataset)
            result[name.removeprefix("patch/")] = copied
        iterator.GoToNextItem()
    if not any(data.GetNumberOfCells() for data in result.values()) and patches != []:
        raise ValueError("OpenFOAM reader returned no displayable mesh cells")
    return result


def read_mesh_surface(
    case_path: Path, patches: list[str] | None = None
) -> vtk.vtkPolyData:
    datasets = read_mesh_patches(case_path, patches)
    result = vtk.vtkPolyData()
    if datasets:
        surface = vtk.vtkAppendPolyData()
        for dataset in datasets.values():
            surface.AddInputData(dataset)
        surface.Update()
        result.ShallowCopy(surface.GetOutput())
    return result
