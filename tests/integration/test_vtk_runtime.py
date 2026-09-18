import logging
import ast
from pathlib import Path

import vtk

from backend.meshing.reader import read_mesh_surface
from backend.vtk_runtime import configure_vtk_logging


def test_all_viewers_use_server_rendering_without_client_array_cache():
    root = Path(__file__).resolve().parents[2]
    sources = [*root.glob("tabs/*_tab.py"), root / "backend/post/postprocessor.py"]
    views = []
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        views.extend(
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr
            in {"VtkLocalView", "VtkRemoteLocalView", "VtkRemoteView"}
        )
    assert len(views) >= 5
    assert set(views) == {"VtkRemoteView"}


def test_vtk_diagnostics_use_logging_without_a_native_window(caplog):
    configure_vtk_logging()
    output = vtk.vtkOutputWindow.GetInstance()
    assert output.GetClassName() == "vtkOutputWindow"
    assert output.GetDisplayMode() == vtk.vtkOutputWindow.NEVER
    configure_vtk_logging()
    assert vtk.vtkOutputWindow.GetInstance() is output
    with caplog.at_level(logging.INFO, logger="FOAMTrame.VTK"):
        output.DisplayErrorText("diagnostic test error")
        output.DisplayWarningText("diagnostic test warning")
    assert [(entry.levelno, entry.message) for entry in caplog.records] == [
        (logging.ERROR, "diagnostic test error"),
        (logging.WARNING, "diagnostic test warning"),
    ]


def write_foam(path: Path, kind: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"FoamFile {{ version 2.0; format ascii; class {kind}; object {path.name}; }}\n{body}\n",
        encoding="utf-8",
    )


def test_mesh_reader_skips_initial_fields_with_openfoam_macros(tmp_path, caplog):
    configure_vtk_logging()
    mesh = tmp_path / "constant" / "polyMesh"
    write_foam(
        mesh / "points", "vectorField", "4\n(\n(0 0 0)\n(1 0 0)\n(0 1 0)\n(0 0 1)\n)"
    )
    write_foam(
        mesh / "faces", "faceList", "4\n(\n3(0 2 1)\n3(0 1 3)\n3(1 2 3)\n3(2 0 3)\n)"
    )
    write_foam(mesh / "owner", "labelList", "4\n(\n0\n0\n0\n0\n)")
    write_foam(mesh / "neighbour", "labelList", "0\n(\n)")
    write_foam(
        mesh / "boundary",
        "polyBoundaryMesh",
        "1\n(\nwalls { type wall; nFaces 4; startFace 0; }\n)",
    )
    for name, kind, value in (
        ("U", "volVectorField", '#calc "vector(1, 0, 0)"'),
        ("T", "volScalarField", "$Tinlet"),
        ("nut", "volScalarField", "0"),
    ):
        write_foam(
            tmp_path / "0" / name,
            kind,
            "dimensions [0 0 0 0 0 0 0];\n"
            f"internalField uniform {value};\n"
            'boundaryField { walls { #includeEtc "caseDicts/setConstraintTypes" } }',
        )
    originals = {path: path.read_bytes() for path in (tmp_path / "0").iterdir()}
    with caplog.at_level(logging.WARNING, logger="FOAMTrame.VTK"):
        output = read_mesh_surface(tmp_path)
    assert output.GetNumberOfCells() >= 4
    assert output.GetBounds() == (0, 1, 0, 1, 0, 1)
    assert not caplog.records
    for name in ("U", "T", "nut"):
        assert output.GetCellData().GetArray(name) is None
    assert all(path.read_bytes() == content for path, content in originals.items())
    write_foam(
        mesh / "boundary",
        "polyBoundaryMesh",
        "2\n(\nbase { type wall; nFaces 1; startFace 0; }\n"
        "sides { type wall; nFaces 3; startFace 1; }\n)",
    )
    assert read_mesh_surface(tmp_path).GetNumberOfCells() == 4
    assert read_mesh_surface(tmp_path, ["base"]).GetNumberOfCells() == 1
    assert read_mesh_surface(tmp_path, ["sides"]).GetNumberOfCells() == 3
    assert read_mesh_surface(tmp_path, []).GetNumberOfCells() == 0
