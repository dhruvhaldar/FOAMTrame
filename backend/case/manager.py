import os
import logging
from pathlib import Path
from typing import Dict, Optional, Union
from backend.utils import sanitize_error

logger = logging.getLogger("FOAMFlask")

class CaseManager:
    """Manages OpenFOAM case creation and directory structures."""

    @staticmethod
    def create_case_structure(case_path: Union[str, Path]) -> Dict[str, Union[bool, str]]:
        """
        Creates a minimal OpenFOAM case structure (0, constant, system).

        Args:
            case_path: Path to the new case directory.

        Returns:
            Dictionary with success status and message.
        """
        try:
            path = Path(case_path).resolve()

            if path.exists() and any(path.iterdir()):
                 # Check if it looks like a case (has 0, constant, system)
                 if (path / "system").exists() and (path / "constant").exists():
                     return {"success": True, "message": "Case directory already exists and appears valid.", "path": str(path)}
                 else:
                     # It exists but might not be a valid case, or is just a random folder.
                     # We will try to add missing folders.
                     pass

            # Create directories
            (path / "0").mkdir(parents=True, exist_ok=True)
            (path / "constant").mkdir(parents=True, exist_ok=True)
            (path / "constant" / "triSurface").mkdir(parents=True, exist_ok=True)
            (path / "system").mkdir(parents=True, exist_ok=True)

            # Create default system files if they don't exist
            CaseManager._create_default_control_dict(path / "system" / "controlDict")
            CaseManager._create_default_fv_schemes(path / "system" / "fvSchemes")
            CaseManager._create_default_fv_solution(path / "system" / "fvSolution")

            # Create empty transportProperties in constant
            CaseManager._create_default_transport_properties(path / "constant" / "transportProperties")

            return {"success": True, "message": f"Case created at {path}", "path": str(path)}

        except Exception as e:
            logger.error(f"Error creating case structure: {e}")
            return {"success": False, "message": sanitize_error(e)}

    @staticmethod
    def _create_default_control_dict(filepath: Path) -> None:
        content = """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2006                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      controlDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

application     simpleFoam;

startFrom       startTime;

startTime       0;

stopAt          endTime;

endTime         1000;

deltaT          1;

writeControl    timeStep;

writeInterval   100;

purgeWrite      0;

writeFormat     ascii;

writePrecision  6;

writeCompression off;

timeFormat      general;

timePrecision   6;

runTimeModifiable true;

// ************************************************************************* //
"""
        # ⚡ Bolt Optimization: Use 'x' mode to atomically create and write without LBYL check
        try:
            with filepath.open("x", encoding="utf-8") as f:
                f.write(content)
        except FileExistsError:
            pass

    @staticmethod
    def _create_default_fv_schemes(filepath: Path) -> None:
        content = """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2006                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      fvSchemes;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

ddtSchemes
{
    default         steadyState;
}

gradSchemes
{
    default         Gauss linear;
}

divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div(phi,k)      bounded Gauss linearUpwind grad(k);
    div(phi,omega)  bounded Gauss linearUpwind grad(omega);
    div(phi,epsilon) bounded Gauss linearUpwind grad(epsilon);
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}

laplacianSchemes
{
    default         Gauss linear corrected;
}

interpolationSchemes
{
    default         linear;
}

snGradSchemes
{
    default         corrected;
}

// ************************************************************************* //
"""
        # ⚡ Bolt Optimization: Use 'x' mode to atomically create and write without LBYL check
        try:
            with filepath.open("x", encoding="utf-8") as f:
                f.write(content)
        except FileExistsError:
            pass

    @staticmethod
    def _create_default_fv_solution(filepath: Path) -> None:
        content = """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2006                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      fvSolution;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.1;
        smoother        GaussSeidel;
    }

    "(U|k|omega|epsilon)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-05;
        relTol          0.1;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 0;
    consistent      yes;

    residualControl
    {
        p               1e-4;
        U               1e-4;
        "(k|epsilon|omega)" 1e-4;
    }
}

relaxationFactors
{
    equations
    {
        U               0.9;
        ".*"            0.9;
    }
}

// ************************************************************************* //
"""
        # ⚡ Bolt Optimization: Use 'x' mode to atomically create and write without LBYL check
        try:
            with filepath.open("x", encoding="utf-8") as f:
                f.write(content)
        except FileExistsError:
            pass

    @staticmethod
    def _create_default_transport_properties(filepath: Path) -> None:
        content = """/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2006                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "constant";
    object      transportProperties;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

transportModel  Newtonian;

nu              [0 2 -1 0 0 0 0] 1e-05;

// ************************************************************************* //
"""
        # ⚡ Bolt Optimization: Use 'x' mode to atomically create and write without LBYL check
        try:
            with filepath.open("x", encoding="utf-8") as f:
                f.write(content)
        except FileExistsError:
            pass
    @staticmethod
    def update_decomposition(case_path: Union[str, Path], num_processes: int) -> Dict[str, Union[bool, str]]:
        """
        Updates the decomposeParDict in the case directory.

        Args:
            case_path: Path to the case directory.
            num_processes: Number of subdomains to use.

        Returns:
            Dictionary with success status and message.
        """
        try:
            path = Path(case_path).resolve()
            dict_path = path / "system" / "decomposeParDict"

            if not dict_path.exists():
                return {"success": False, "message": "decomposeParDict not found in system directory."}

            with dict_path.open("r", encoding="utf-8") as f:
                content = f.read()

            # Update numberOfSubdomains
            import re
            content = re.sub(r"(numberOfSubdomains\s+)\d+;", rf"\g<1>{num_processes};", content)

            # Change method/decomposer to scotch if it's hierarchical or simple, 
            # as scotch is more robust for arbitrary process counts.
            # Handle both 'method' and 'decomposer' (OpenFOAM versions vary)
            if re.search(r"(method|decomposer)\s+\w+;", content):
                content = re.sub(r"((?:method|decomposer)\s+)\w+;", r"\g<1>scotch;", content)
            else:
                # If no method/decomposer line, add it
                if "numberOfSubdomains" in content:
                    content = re.sub(r"(numberOfSubdomains\s+\d+;)", r"\1\n\nmethod          scotch;", content)

            with dict_path.open("w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"[FOAMFlask] Updated decomposition to {num_processes} processes (scotch) in {dict_path}")
            return {"success": True, "message": f"Decomposition updated to {num_processes} processes."}

        except Exception as e:
            logger.error(f"Error updating decomposition: {e}")
            return {"success": False, "message": sanitize_error(e)}
