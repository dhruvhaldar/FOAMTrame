from __future__ import annotations

import gzip
import math
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import vtk


SURFACE_EXTENSIONS = (".stl", ".obj", ".stl.gz", ".obj.gz")
_REGION_CHARACTER = re.compile(r"[^A-Za-z0-9_]")
_READERS = {
    ".stl": vtk.vtkSTLReader,
    ".obj": vtk.vtkOBJReader,
}


@dataclass(frozen=True)
class MeshingConfiguration:
    surface_file: str
    bounds: tuple[float, float, float, float, float, float]
    base_cells: tuple[int, int, int]
    refinement_min: int
    refinement_max: int
    surface_layers: int
    feature_angle: int = 30

    def to_state(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MeshingWriteResult:
    paths: tuple[Path, ...]
    backup_directory: Path | None
    staged_surface: Path | None


def _validated_case(case_path: str | Path) -> Path:
    path = Path(case_path).resolve()
    if not path.is_dir():
        raise ValueError("Select a valid active case.")
    return path


def _validated_surface(case_path: Path, selection: str) -> Path:
    relative = PurePosixPath(str(selection or ""))
    if (
        not selection
        or relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.parts[0] not in {"geometry", "triSurface"}
        or len(relative.parts) < 2
        or any(ord(character) < 32 for character in selection)
        or any(character in selection for character in ('"', "'", "\\"))
        or not selection.lower().endswith(SURFACE_EXTENSIONS)
    ):
        raise ValueError("Select a supported case surface.")
    constant = (case_path / "constant").resolve()
    if constant.parent != case_path:
        raise ValueError("The case constant directory resolves outside the case.")
    surface_root = (constant / relative.parts[0]).resolve()
    if surface_root.parent != constant:
        raise ValueError("The case geometry directory resolves outside constant.")
    surface = (constant / Path(*relative.parts)).resolve()
    try:
        surface.relative_to(surface_root)
    except ValueError as exc:
        raise ValueError(
            "The selected surface is outside its case geometry directory."
        ) from exc
    if not surface.is_file():
        raise ValueError("The selected case surface no longer exists.")
    return surface


def list_meshing_surfaces(case_path: str | Path | None) -> list[dict[str, str]]:
    if not case_path:
        return []
    case = _validated_case(case_path)
    options: list[dict[str, str]] = []
    constant = case / "constant"
    if constant.resolve().parent != case:
        return []
    for folder in ("geometry", "triSurface"):
        root = constant / folder
        if not root.is_dir():
            continue
        resolved_root = root.resolve()
        if resolved_root.parent != constant.resolve():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or not path.name.lower().endswith(SURFACE_EXTENSIONS):
                continue
            try:
                relative = path.resolve().relative_to(resolved_root).as_posix()
            except ValueError:
                continue
            selection = f"{folder}/{relative}"
            options.append({"text": f"constant/{selection}", "value": selection})
    return sorted(options, key=lambda item: item["value"].lower())


def _surface_reader_path(surface: Path):
    temporary_path: Path | None = None
    if surface.suffix.lower() != ".gz":
        return surface, temporary_path
    extension = Path(surface.stem).suffix.lower()
    if extension not in _READERS:
        raise ValueError(f"Unsupported compressed surface '{surface.name}'.")
    with gzip.open(surface, "rb") as source:  # nosec: a single validated stream
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as expanded:
            shutil.copyfileobj(source, expanded)
            temporary_path = Path(expanded.name)
    return temporary_path, temporary_path


def load_surface_dataset(case_path: str | Path, selection: str):
    case = _validated_case(case_path)
    surface = _validated_surface(case, selection)
    reader_path, temporary_path = _surface_reader_path(surface)
    try:
        extension = reader_path.suffix.lower()
        reader_class = _READERS.get(extension)
        if reader_class is None:
            raise ValueError(f"Unsupported surface type '{extension}'.")
        reader = reader_class()
        reader.SetFileName(str(reader_path))
        reader.Update()
        output = reader.GetOutput()
        if output is None or output.GetNumberOfPoints() == 0:
            raise ValueError(f"{surface.name} contains no readable surface points.")
        edges = vtk.vtkFeatureEdges()
        edges.SetInputData(output)
        edges.FeatureEdgesOff()
        edges.ManifoldEdgesOff()
        edges.BoundaryEdgesOn()
        edges.NonManifoldEdgesOn()
        edges.Update()
        if edges.GetOutput().GetNumberOfCells():
            raise ValueError(
                f"{surface.name} is not a closed manifold surface; "
                "repair it before generating a volume mesh."
            )
        dataset = output.NewInstance()
        dataset.ShallowCopy(output)
        return dataset
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def surface_bounds(
    case_path: str | Path, selection: str
) -> tuple[float, float, float, float, float, float]:
    output = load_surface_dataset(case_path, selection)
    bounds = tuple(float(value) for value in output.GetBounds())
    if len(bounds) != 6 or not all(math.isfinite(value) for value in bounds):
        raise ValueError(f"{selection} has invalid geometric bounds.")
    return (
        bounds[0],
        bounds[1],
        bounds[2],
        bounds[3],
        bounds[4],
        bounds[5],
    )


def suggest_meshing_configuration(
    case_path: str | Path,
    selection: str,
    *,
    padding_percent: float = 20,
    fineness: int = 5,
    refinement_min: int = 2,
    refinement_max: int = 3,
    surface_layers: int = 3,
) -> MeshingConfiguration:
    geometry_bounds = surface_bounds(case_path, selection)
    spans = tuple(
        geometry_bounds[index + 1] - geometry_bounds[index] for index in (0, 2, 4)
    )
    longest_span = max(spans)
    if longest_span <= 0:
        raise ValueError("The selected surface has no measurable extent.")
    padding_ratio = min(max(float(padding_percent), 5.0), 500.0) / 100.0
    expanded: list[float] = []
    for axis, index in enumerate((0, 2, 4)):
        padding = max(spans[axis] * padding_ratio, longest_span * 0.05)
        expanded.extend(
            (geometry_bounds[index] - padding, geometry_bounds[index + 1] + padding)
        )
    expanded_spans = tuple(expanded[index + 1] - expanded[index] for index in (0, 2, 4))
    longest_cells = 12 + min(max(int(fineness), 1), 10) * 8
    base_cells = tuple(
        min(300, max(4, round(longest_cells * span / max(expanded_spans))))
        for span in expanded_spans
    )
    return validate_meshing_configuration(
        MeshingConfiguration(
            surface_file=selection,
            bounds=(
                expanded[0],
                expanded[1],
                expanded[2],
                expanded[3],
                expanded[4],
                expanded[5],
            ),
            base_cells=(base_cells[0], base_cells[1], base_cells[2]),
            refinement_min=refinement_min,
            refinement_max=refinement_max,
            surface_layers=surface_layers,
        )
    )


def validate_meshing_configuration(
    configuration: MeshingConfiguration,
) -> MeshingConfiguration:
    surface_file = str(configuration.surface_file)
    relative_surface = PurePosixPath(surface_file)
    if (
        not surface_file
        or relative_surface.is_absolute()
        or ".." in relative_surface.parts
        or any(ord(character) < 32 for character in surface_file)
        or any(character in surface_file for character in ('"', "'", "\\"))
        or not surface_file.lower().endswith(SURFACE_EXTENSIONS)
    ):
        raise ValueError("Select a supported case surface.")
    bounds = tuple(float(value) for value in configuration.bounds)
    cells = tuple(int(value) for value in configuration.base_cells)
    if len(bounds) != 6 or not all(math.isfinite(value) for value in bounds):
        raise ValueError("Domain bounds must contain six finite numbers.")
    if any(bounds[index] >= bounds[index + 1] for index in (0, 2, 4)):
        raise ValueError("Each domain minimum must be smaller than its maximum.")
    if len(cells) != 3 or any(value < 1 or value > 300 for value in cells):
        raise ValueError("Base mesh cell counts must be between 1 and 300 per axis.")
    refinement_min = int(configuration.refinement_min)
    refinement_max = int(configuration.refinement_max)
    if not 0 <= refinement_min <= refinement_max <= 8:
        raise ValueError("Surface refinement levels must satisfy 0 ≤ min ≤ max ≤ 8.")
    surface_layers = int(configuration.surface_layers)
    if not 0 <= surface_layers <= 20:
        raise ValueError("Boundary layers must be between 0 and 20.")
    feature_angle = int(configuration.feature_angle)
    if not 10 <= feature_angle <= 180:
        raise ValueError("Feature angle must be between 10° and 180°.")
    return MeshingConfiguration(
        surface_file=surface_file,
        bounds=bounds,
        base_cells=cells,
        refinement_min=refinement_min,
        refinement_max=refinement_max,
        surface_layers=surface_layers,
        feature_angle=feature_angle,
    )


def _number(value: float) -> str:
    return format(value, ".12g")


def _region_name(surface_file: str) -> str:
    name = Path(PurePosixPath(surface_file).name).stem
    if name.lower().endswith((".stl", ".obj", ".ply")):
        name = Path(name).stem
    name = _REGION_CHARACTER.sub("_", name)
    if not name or name[0].isdigit():
        name = f"surface_{name}"
    return name[:64]


def _snappy_surface_file(selection: str) -> str:
    relative = PurePosixPath(selection)
    if relative.parts[0] == "geometry":
        return PurePosixPath(*relative.parts[1:]).as_posix()
    return relative.name


def build_block_mesh_dict(configuration: MeshingConfiguration) -> str:
    config = validate_meshing_configuration(configuration)
    xmin, xmax, ymin, ymax, zmin, zmax = map(_number, config.bounds)
    nx, ny, nz = config.base_cells
    return f"""FoamFile
{{
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}

// Generated by FOAMTrame's reviewed meshing workflow.
scale 1;

vertices
(
    ({xmin} {ymin} {zmin})
    ({xmax} {ymin} {zmin})
    ({xmax} {ymax} {zmin})
    ({xmin} {ymax} {zmin})
    ({xmin} {ymin} {zmax})
    ({xmax} {ymin} {zmax})
    ({xmax} {ymax} {zmax})
    ({xmin} {ymax} {zmax})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

edges ();

boundary
(
    farfield
    {{
        type patch;
        faces
        (
            (0 4 7 3)
            (1 2 6 5)
            (0 1 5 4)
            (3 7 6 2)
            (0 3 2 1)
            (4 5 6 7)
        );
    }}
);

mergePatchPairs ();
"""


def build_snappy_hex_mesh_dict(configuration: MeshingConfiguration) -> str:
    config = validate_meshing_configuration(configuration)
    surface_file = _snappy_surface_file(config.surface_file)
    region = _region_name(surface_file)
    xmin, xmax, ymin, ymax, zmin, zmax = config.bounds
    location = tuple(
        minimum + (maximum - minimum) * 0.37 / cells
        for minimum, maximum, cells in (
            (xmin, xmax, config.base_cells[0]),
            (ymin, ymax, config.base_cells[1]),
            (zmin, zmax, config.base_cells[2]),
        )
    )
    location_text = " ".join(_number(value) for value in location)
    layer_entry = (
        f"""
        \"{region}.*\"
        {{
            nSurfaceLayers {config.surface_layers};
        }}"""
        if config.surface_layers
        else ""
    )
    return f"""FoamFile
{{
    format      ascii;
    class       dictionary;
    object      snappyHexMeshDict;
}}

// Generated by FOAMTrame's reviewed meshing workflow.
castellatedMesh true;
snap            true;
addLayers       {str(bool(config.surface_layers)).lower()};

geometry
{{
    {region}
    {{
        type triSurfaceMesh;
        file \"{surface_file}\";
    }}
}}

castellatedMeshControls
{{
    maxLocalCells       1000000;
    maxGlobalCells      4000000;
    minRefinementCells  0;
    maxLoadUnbalance    0.10;
    nCellsBetweenLevels 3;
    features            ();
    refinementSurfaces
    {{
        {region}
        {{
            level ({config.refinement_min} {config.refinement_max});
            patchInfo {{ type wall; }}
        }}
    }}
    resolveFeatureAngle {config.feature_angle};
    refinementRegions   {{}}
    insidePoint         ({location_text});
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch       3;
    tolerance          2.0;
    nSolveIter         30;
    nRelaxIter         5;
    nFeatureSnapIter   10;
    implicitFeatureSnap true;
    explicitFeatureSnap false;
    multiRegionFeatureSnap false;
}}

addLayersControls
{{
    relativeSizes true;
    layers
    {{{layer_entry}
    }}
    expansionRatio 1.2;
    finalLayerThickness 0.3;
    minThickness 0.1;
    nGrow 0;
    featureAngle {config.feature_angle};
    slipFeatureAngle 30;
    nRelaxIter 5;
    nSmoothSurfaceNormals 1;
    nSmoothNormals 3;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedialAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter 50;
}}

meshQualityControls
{{
    #includeEtc \"caseDicts/mesh/generation/meshQualityDict.cfg\"
}}

writeFlags (scalarLevels layerSets layerFields);
mergeTolerance 1e-6;
"""


def write_meshing_dictionaries(
    case_path: str | Path, configuration: MeshingConfiguration
) -> MeshingWriteResult:
    case = _validated_case(case_path)
    config = validate_meshing_configuration(configuration)
    surface = _validated_surface(case, config.surface_file)
    staged_surface: Path | None = None
    if PurePosixPath(config.surface_file).parts[0] == "triSurface":
        geometry = case / "constant" / "geometry"
        geometry.mkdir(parents=True, exist_ok=True)
        if geometry.resolve().parent != (case / "constant").resolve():
            raise ValueError("The geometry directory resolves outside the active case.")
        staged_surface = geometry / surface.name
        if staged_surface.exists() or staged_surface.is_symlink():
            raise ValueError(
                f"constant/geometry/{surface.name} already exists. "
                "Select it directly or rename the imported surface before saving."
            )
    system = case / "system"
    system.mkdir(parents=True, exist_ok=True)
    if system.resolve().parent != case:
        raise ValueError("The system directory resolves outside the active case.")
    contents = {
        "blockMeshDict": build_block_mesh_dict(config),
        "snappyHexMeshDict": build_snappy_hex_mesh_dict(config),
    }
    existing = [system / name for name in contents if (system / name).is_file()]
    for name in contents:
        destination = system / name
        if destination.exists() and (
            not destination.is_file() or destination.is_symlink()
        ):
            raise ValueError(f"Cannot replace non-regular system/{name}.")
    backup_directory: Path | None = None
    if existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_directory = system / ".foamtrame-backups" / stamp
        if backup_directory.resolve().parent.parent != system.resolve():
            raise ValueError("The dictionary backup directory resolves outside system.")
        backup_directory.mkdir(parents=True)
        for source in existing:
            shutil.copy2(  # nosec: fixed dictionary names and backup path validated inside case
                source, backup_directory / source.name
            )

    if staged_surface is not None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{staged_surface.name}.", suffix=".tmp", dir=staged_surface.parent
        )
        temporary = Path(temporary_name)
        try:
            with (
                os.fdopen(descriptor, "wb") as output,
                surface.open("rb") as input_stream,
            ):
                shutil.copyfileobj(input_stream, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, staged_surface)
        finally:
            temporary.unlink(missing_ok=True)

    written: list[Path] = []
    for name, content in contents.items():
        destination = system / name
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{name}.", suffix=".tmp", dir=system
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            written.append(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return MeshingWriteResult(tuple(written), backup_directory, staged_surface)
