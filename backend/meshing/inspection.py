"""Read local OpenFOAM mesh structure and summarize ``checkMesh`` output."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypedDict


_LIST_COUNT = re.compile(rb"(?:^|\n)\s*(\d+)\s*(?:\r?\n)\s*\(")
_PATCH_BLOCK = re.compile(
    r"(?m)^\s*([A-Za-z_][A-Za-z0-9_.:+-]*)\s*\{([^{}]*)\}", re.DOTALL
)
_PATCH_TYPE = re.compile(r"\btype\s+([A-Za-z_][A-Za-z0-9_.:+-]*)\s*;")
_PATCH_FACES = re.compile(r"\bnFaces\s+(\d+)\s*;")
_CHECK_VALUE_PATTERNS = {
    "points": re.compile(r"^\s*points:\s*([\d,]+)", re.MULTILINE | re.IGNORECASE),
    "faces": re.compile(r"^\s*faces:\s*([\d,]+)", re.MULTILINE | re.IGNORECASE),
    "internal_faces": re.compile(
        r"^\s*internal faces:\s*([\d,]+)", re.MULTILINE | re.IGNORECASE
    ),
    "cells": re.compile(r"^\s*cells:\s*([\d,]+)", re.MULTILINE | re.IGNORECASE),
    "patches": re.compile(
        r"^\s*boundary patches:\s*([\d,]+)", re.MULTILINE | re.IGNORECASE
    ),
}
_NON_ORTHOGONALITY = re.compile(
    r"Mesh non-orthogonality Max:\s*([-+\d.eE]+)\s+average:\s*([-+\d.eE]+)",
    re.IGNORECASE,
)
_SKEWNESS = re.compile(r"Max skewness\s*=\s*([-+\d.eE]+)", re.IGNORECASE)
_ASPECT_RATIO = re.compile(r"Max aspect ratio\s*=\s*([-+\d.eE]+)", re.IGNORECASE)
_FAILED_CHECKS = re.compile(r"Failed\s+(\d+)\s+mesh checks?", re.IGNORECASE)


@dataclass(frozen=True)
class MeshPatch:
    name: str
    patch_type: str
    face_count: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MeshInspection:
    available: bool
    status: str
    points: int | None
    faces: int | None
    internal_faces: int | None
    cells: int | None
    patches: tuple[MeshPatch, ...]
    missing_files: tuple[str, ...]

    def to_state(self) -> dict[str, object]:
        return {
            "available": self.available,
            "status": self.status,
            "points": self.points,
            "faces": self.faces,
            "internal_faces": self.internal_faces,
            "cells": self.cells,
            "patches": [patch.to_dict() for patch in self.patches],
            "missing_files": list(self.missing_files),
        }


class ReportSection(TypedDict):
    title: str
    rows: list[dict[str, str]]


@dataclass(frozen=True)
class MeshQualityReport:
    available: bool
    passed: bool
    status: str
    failed_checks: int
    max_non_orthogonality: float | None
    average_non_orthogonality: float | None
    max_skewness: float | None
    max_aspect_ratio: float | None
    points: int | None
    faces: int | None
    cells: int | None
    source: str
    sections: tuple[ReportSection, ...] = ()
    warnings: tuple[str, ...] = ()
    log_text: str = ""

    def to_state(self) -> dict[str, object]:
        return asdict(self)


def _foam_list_count(path: Path) -> int | None:
    try:
        # The list size remains ASCII in both ASCII and binary OpenFOAM files and
        # appears before the potentially large payload, so a small prefix is enough.
        prefix = path.read_bytes()[:65536]
    except OSError:
        return None
    match = _LIST_COUNT.search(prefix)
    return int(match.group(1)) if match else None


def _read_patches(path: Path) -> tuple[MeshPatch, ...]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    patches: list[MeshPatch] = []
    for match in _PATCH_BLOCK.finditer(content):
        name, body = match.groups()
        patch_type = _PATCH_TYPE.search(body)
        face_count = _PATCH_FACES.search(body)
        if patch_type is None and face_count is None:
            continue
        patches.append(
            MeshPatch(
                name=name,
                patch_type=patch_type.group(1) if patch_type else "unknown",
                face_count=int(face_count.group(1)) if face_count else None,
            )
        )
    return tuple(patches)


def _latest_check_mesh_log(case_path: Path) -> Path | None:
    log_dir = case_path / "logs"
    if not log_dir.is_dir():
        return None
    candidates: list[Path] = []
    for path in log_dir.glob("run_*.log"):
        try:
            prefix = path.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            continue
        if ">>> checkMesh" in prefix:
            candidates.append(path)
    return (
        max(candidates, key=lambda path: path.stat().st_mtime_ns)
        if candidates
        else None
    )


def inspect_case_mesh(case_path: str | Path | None) -> MeshInspection:
    if not case_path:
        return MeshInspection(
            False, "Select an active case", None, None, None, None, (), ()
        )
    poly_mesh = Path(case_path).resolve() / "constant" / "polyMesh"
    required = ("points", "faces", "owner", "neighbour", "boundary")
    missing = tuple(name for name in required if not (poly_mesh / name).is_file())
    available = not missing
    status = (
        "Mesh structure detected"
        if available
        else "Mesh is incomplete: " + ", ".join(missing)
    )
    return MeshInspection(
        available=available,
        status=status,
        points=_foam_list_count(poly_mesh / "points"),
        faces=_foam_list_count(poly_mesh / "faces"),
        internal_faces=_foam_list_count(poly_mesh / "neighbour"),
        cells=None,
        patches=_read_patches(poly_mesh / "boundary"),
        missing_files=missing,
    )


def parse_check_mesh_output(output: str, *, source: str = "") -> MeshQualityReport:
    # Each time has its own verdict. Never combine an earlier pass with a later
    # incomplete check when a log contains several mesh times.
    times = list(re.finditer(r"(?m)^Time = .+$", output))
    report_output = output[times[-1].start() :] if times else output
    output = report_output
    failed_match = _FAILED_CHECKS.search(output)
    failed_checks = int(failed_match.group(1)) if failed_match else 0
    passed = "Mesh OK." in output and failed_checks == 0
    non_orthogonality = _NON_ORTHOGONALITY.search(output)

    def metric(pattern: re.Pattern[str]) -> float | None:
        match = pattern.search(output)
        return float(match.group(1)) if match else None

    values: dict[str, int | None] = {}
    for name, pattern in _CHECK_VALUE_PATTERNS.items():
        match = pattern.search(output)
        values[name] = int(match.group(1).replace(",", "")) if match else None
    available = bool(output.strip())
    if not available:
        status = "Run checkMesh to evaluate mesh quality"
    elif passed:
        status = "Mesh passed checkMesh"
    elif failed_checks:
        status = f"Mesh failed {failed_checks} quality check(s)"
    else:
        status = "checkMesh did not report a clean pass"
    return MeshQualityReport(
        available=available,
        passed=passed,
        status=status,
        failed_checks=failed_checks,
        max_non_orthogonality=(
            float(non_orthogonality.group(1)) if non_orthogonality else None
        ),
        average_non_orthogonality=(
            float(non_orthogonality.group(2)) if non_orthogonality else None
        ),
        max_skewness=metric(_SKEWNESS),
        max_aspect_ratio=metric(_ASPECT_RATIO),
        points=values["points"],
        faces=values["faces"],
        cells=values["cells"],
        source=source,
        sections=_report_sections(output),
        warnings=tuple(
            line.strip()
            for line in output.splitlines()
            if line.lstrip().startswith("*")
            or re.search(r"\b(?:warning|failed|fatal error)\b", line, re.I)
        ),
        log_text=output,
    )


def _report_sections(output: str) -> tuple[ReportSection, ...]:
    """Retain every reported check/value without inventing quality thresholds."""
    sections: list[ReportSection] = []
    rows: list[dict[str, str]] = []
    for line in output.splitlines():
        text = line.strip()
        if text.startswith(("Mesh stats", "Overall number of cells", "Checking ")):
            rows = []
            sections.append({"title": text.rstrip(". :"), "rows": rows})
        elif sections and text and text not in ("End", "Mesh OK."):
            status = "Reported"
            if re.search(r"\b(?:failed|error)\b", text, re.I):
                status = "Failed"
            elif text.startswith("*") or re.search(r"\bwarning\b", text, re.I):
                status = "Warning"
            elif re.search(r"\bok\b", text, re.I):
                status = "Passed"
            rows.append({"text": text, "status": status})
    return tuple(sections)


def summarize_quality_report(report: MeshQualityReport) -> list[dict[str, str]]:
    """Condense the report without inferring verdicts for numeric measurements."""
    summaries: list[dict[str, str]] = []
    counts = []
    for key, label in (
        ("cells", "cells"),
        ("points", "points"),
        ("faces", "faces"),
        ("patches", "boundary patches"),
    ):
        match = _CHECK_VALUE_PATTERNS[key].search(report.log_text)
        if match:
            counts.append(f"{int(match.group(1).replace(',', '')):,} {label}")
    if counts:
        summaries.append({"title": "Mesh size", "summary": " · ".join(counts)})
    cell_types = []
    for match in re.finditer(
        r"(?m)^\s*(hexahedra|prisms|wedges|pyramids|tet wedges|tetrahedra|polyhedra):\s*([\d,]+)",
        report.log_text,
    ):
        count = int(match.group(2).replace(",", ""))
        if count:
            share = f" ({count / report.cells:.1%})" if report.cells else ""
            cell_types.append(f"{count:,} {match.group(1)}{share}")
    if cell_types:
        summaries.append(
            {"title": "Cell composition", "summary": " · ".join(cell_types)}
        )
    metrics = []
    for label, value, unit in (
        ("Max non-orthogonality", report.max_non_orthogonality, "°"),
        ("Average non-orthogonality", report.average_non_orthogonality, "°"),
        ("Max skewness", report.max_skewness, ""),
        ("Max aspect ratio", report.max_aspect_ratio, ""),
    ):
        if value is not None:
            metrics.append(f"{label}: {value:.4g}{unit}")
    if metrics:
        summaries.append({"title": "Quality metrics", "summary": " · ".join(metrics)})
    for section in report.sections:
        if not section["title"].startswith("Checking "):
            continue
        counts_by_status = {
            status: sum(row["status"] == status for row in section["rows"])
            for status in ("Passed", "Warning", "Failed")
        }
        details = [
            f"{count} {status.lower()}"
            for status, count in counts_by_status.items()
            if count
        ]
        summaries.append(
            {
                "title": section["title"].removeprefix("Checking ").capitalize(),
                "summary": " · ".join(details) + " explicitly reported."
                if details
                else "No explicit check verdicts recorded.",
            }
        )
    return summaries


def load_latest_quality_report(case_path: str | Path | None) -> MeshQualityReport:
    if not case_path:
        return parse_check_mesh_output("")
    case = Path(case_path).resolve()
    log_path = _latest_check_mesh_log(case)
    if log_path is None:
        return parse_check_mesh_output("")
    try:
        poly_mesh = case / "constant" / "polyMesh"
        mesh_files = [
            poly_mesh / name
            for name in ("points", "faces", "owner", "neighbour", "boundary")
        ]
        if any(not path.is_file() for path in mesh_files) or any(
            path.stat().st_mtime_ns > log_path.stat().st_mtime_ns for path in mesh_files
        ):
            return parse_check_mesh_output("")
        output = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return parse_check_mesh_output("")
    return parse_check_mesh_output(output, source=log_path.name)
