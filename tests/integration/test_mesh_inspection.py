from pathlib import Path
import os

from backend.meshing.inspection import (
    inspect_case_mesh,
    load_latest_quality_report,
    parse_check_mesh_output,
)


def _write_list(path: Path, count: int, payload: str = "") -> None:
    path.write_text(
        f"FoamFile\n{{\n    format ascii;\n}}\n{count}\n(\n{payload}\n)\n",
        encoding="utf-8",
    )


def _build_mesh(case: Path) -> Path:
    poly_mesh = case / "constant" / "polyMesh"
    poly_mesh.mkdir(parents=True)
    _write_list(poly_mesh / "points", 8)
    _write_list(poly_mesh / "faces", 6)
    _write_list(poly_mesh / "owner", 6)
    _write_list(poly_mesh / "neighbour", 0)
    (poly_mesh / "boundary").write_text(
        """
        FoamFile { format ascii; }
        2
        (
            inlet
            {
                type patch;
                nFaces 1;
                startFace 0;
            }
            walls
            {
                type wall;
                nFaces 5;
                startFace 1;
            }
        )
        """,
        encoding="utf-8",
    )
    return case


def test_inspect_case_mesh_reports_structure_and_patches(tmp_path):
    case = _build_mesh(tmp_path / "case")

    inspection = inspect_case_mesh(case)

    assert inspection.available is True
    assert inspection.points == 8
    assert inspection.faces == 6
    assert inspection.internal_faces == 0
    assert [
        (patch.name, patch.patch_type, patch.face_count) for patch in inspection.patches
    ] == [
        ("inlet", "patch", 1),
        ("walls", "wall", 5),
    ]


def test_inspect_case_mesh_identifies_incomplete_polymesh(tmp_path):
    case = tmp_path / "case"
    (case / "constant" / "polyMesh").mkdir(parents=True)
    _write_list(case / "constant" / "polyMesh" / "points", 4)

    inspection = inspect_case_mesh(case)

    assert inspection.available is False
    assert inspection.missing_files == ("faces", "owner", "neighbour", "boundary")
    assert "Mesh is incomplete" in inspection.status


def test_parse_check_mesh_output_extracts_quality_metrics():
    output = """
    Mesh stats
        points:           1,024
        faces:            4,096
        internal faces:   3,500
        cells:            2,048
        boundary patches: 4
    Max aspect ratio = 12.5 OK.
    Mesh non-orthogonality Max: 63.1 average: 8.4
    Max skewness = 2.01 OK.
    Mesh OK.
    """

    report = parse_check_mesh_output(output, source="run_1.log")

    assert report.available is True
    assert report.passed is True
    assert report.status == "Mesh passed checkMesh"
    assert report.cells == 2048
    assert report.max_non_orthogonality == 63.1
    assert report.average_non_orthogonality == 8.4
    assert report.max_skewness == 2.01
    assert report.max_aspect_ratio == 12.5


def test_latest_quality_report_uses_newest_checkmesh_archive(tmp_path):
    case = _build_mesh(tmp_path / "case")
    logs = case / "logs"
    logs.mkdir()
    (logs / "run_1.log").write_text(
        "[FOAMTrame] >>> blockMesh\nMesh OK.\n", encoding="utf-8"
    )
    (logs / "run_2.log").write_text(
        "[FOAMTrame] >>> checkMesh\ncells: 12\nFailed 2 mesh checks.\n",
        encoding="utf-8",
    )

    report = load_latest_quality_report(case)

    assert report.available is True
    assert report.passed is False
    assert report.failed_checks == 2
    assert report.cells == 12
    assert report.source == "run_2.log"


def test_quality_report_is_cleared_after_mesh_changes(tmp_path):
    case = _build_mesh(tmp_path / "case")
    logs = case / "logs"
    logs.mkdir()
    archive = logs / "run_1.log"
    archive.write_text("[FOAMTrame] >>> checkMesh\nMesh OK.\n", encoding="utf-8")
    points = case / "constant" / "polyMesh" / "points"
    changed_time = archive.stat().st_mtime_ns + 2_000_000_000
    os.utime(points, ns=(changed_time, changed_time))

    assert load_latest_quality_report(case).available is False


def test_detailed_report_keeps_warnings_even_on_pass():
    output = """Time = 0s
Mesh stats
    points: 890220
    cells: 737661
Overall number of cells of each type:
    hexahedra: 618362
Checking topology...
    Boundary definition OK.
Checking patch topology for multiply connected surfaces...
    farfield 10504 10506 ok (closed singly connected)
Checking geometry...
    Mesh non-orthogonality Max: 73.54685714 average: 9.952914398
   *Number of severely non-orthogonal (> 70 degrees) faces: 2.
    Non-orthogonality check OK.
Mesh OK.
End
"""
    report = parse_check_mesh_output(output)
    assert report.passed
    assert report.cells == 737661
    assert len(report.warnings) == 1
    assert "faces: 2" in report.warnings[0]
    assert len(report.sections) == 5
    assert report.sections[-1]["rows"][-1]["status"] == "Passed"
    assert report.sections[-1]["rows"][-2]["status"] == "Warning"
    assert report.log_text == output


def test_last_mesh_time_cannot_inherit_an_earlier_pass():
    report = parse_check_mesh_output(
        "Time = 0s\nMesh stats\ncells: 10\nMesh OK.\n"
        "Time = 1s\nMesh stats\ncells: 20\nChecking geometry...\n"
        "***Error: negative volume\nFailed 1 mesh checks.\n"
    )
    assert not report.passed
    assert report.cells == 20
    assert report.failed_checks == 1
    assert report.sections[-1]["rows"][0]["status"] == "Failed"
