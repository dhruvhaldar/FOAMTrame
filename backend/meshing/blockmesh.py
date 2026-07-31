import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple

logger = logging.getLogger("FOAMFlask")

class BlockMeshGenerator:
    """Generates system/blockMeshDict based on configuration."""

    @staticmethod
    def _validate_numeric_tuple(values: Any, length: int, expected_type: type, name: str) -> Tuple[Any, ...]:
        """Validates that values is a tuple of correct length and type."""
        if not isinstance(values, (list, tuple)):
             # Try to convert single items or strings that might look like lists if reasonable,
             # but here we expect structured input.
             # Fail safe.
             raise ValueError(f"{name} must be a list or tuple")

        if len(values) != length:
            raise ValueError(f"{name} must have {length} elements")

        safe_values = []
        for v in values:
            try:
                # Enforce type conversion (this strips strings/malicious payloads)
                safe_values.append(expected_type(v))
            except (ValueError, TypeError):
                raise ValueError(f"Invalid value in {name}: {v} is not of type {expected_type.__name__}")

        return tuple(safe_values)

    @staticmethod
    def generate_dict(
        case_path: Path,
        min_point: Tuple[float, float, float],
        max_point: Tuple[float, float, float],
        cells: Tuple[int, int, int],
        grading: Tuple[float, float, float] = (1, 1, 1)
    ) -> bool:
        """
        Generates the blockMeshDict file.

        Args:
            case_path: Path to the case directory.
            min_point: (x, y, z) tuple for minimum bounds.
            max_point: (x, y, z) tuple for maximum bounds.
            cells: (nx, ny, nz) tuple for number of cells.
            grading: (gx, gy, gz) tuple for grading.

        Returns:
            True if successful, False otherwise.
        """
        try:
            system_dir = case_path / "system"
            if not system_dir.exists():
                logger.error(f"System directory not found: {system_dir}")
                return False

            dict_path = system_dir / "blockMeshDict"

            # Security: Validate inputs are numeric
            # This prevents injection of arbitrary OpenFOAM syntax like #codeStream
            safe_min = BlockMeshGenerator._validate_numeric_tuple(min_point, 3, float, "min_point")
            safe_max = BlockMeshGenerator._validate_numeric_tuple(max_point, 3, float, "max_point")
            safe_cells = BlockMeshGenerator._validate_numeric_tuple(cells, 3, int, "cells")
            safe_grading = BlockMeshGenerator._validate_numeric_tuple(grading, 3, float, "grading")

            # Unpack values
            min_x, min_y, min_z = safe_min
            max_x, max_y, max_z = safe_max
            nx, ny, nz = safe_cells
            gx, gy, gz = safe_grading

            content = f"""/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2012                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

convertToMeters 1;

vertices
(
    ({min_x} {min_y} {min_z})
    ({max_x} {min_y} {min_z})
    ({max_x} {max_y} {min_z})
    ({min_x} {max_y} {min_z})
    ({min_x} {min_y} {max_z})
    ({max_x} {min_y} {max_z})
    ({max_x} {max_y} {max_z})
    ({min_x} {max_y} {max_z})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading ({gx} {gy} {gz})
);

edges
(
);

boundary
(
    allBoundary
    {{
        type patch;
        faces
        (
            (3 7 6 2)
            (0 4 7 3)
            (2 6 5 1)
            (1 5 4 0)
            (0 3 2 1)
            (4 5 6 7)
        );
    }}
);

mergePatchPairs
(
);

// ************************************************************************* //
"""
            with open(dict_path, "w") as f:
                f.write(content)

            logger.info(f"Generated blockMeshDict at {dict_path}")
            return True

        except Exception as e:
            logger.error(f"Error generating blockMeshDict: {e}")
            return False
