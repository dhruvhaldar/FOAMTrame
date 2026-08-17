import logging
from pathlib import Path
from typing import Dict, Any
from werkzeug.utils import secure_filename

logger = logging.getLogger("FOAMTrame")

class SnappyHexMeshGenerator:
    """Generates system/snappyHexMeshDict based on configuration."""

    @staticmethod
    def generate_dict(
        case_path: Path,
        config: Dict[str, Any],
        openfoam_version: str = "12"
    ) -> bool:
        """
        Generates the snappyHexMeshDict file.

        Args:
            case_path: Path to the case directory.
            config: Configuration dictionary.
                    Can be legacy (stl_filename, refinement_level keys)
                    or new complex structure.

        Returns:
            True if successful, False otherwise.
        """
        try:
            system_dir = case_path / "system"
            if not system_dir.exists():
                logger.error(f"System directory not found: {system_dir}")
                return False

            dict_path = system_dir / "snappyHexMeshDict"

            # Parse Configuration

            global_settings = config.get("global_settings", {})
            objects = config.get("objects", [])

            # Security: Validate location_in_mesh
            raw_location = config.get("location_in_mesh", [0, 0, 0])
            if not isinstance(raw_location, (list, tuple)) or len(raw_location) != 3:
                location_in_mesh = [0, 0, 0]
            else:
                try:
                    # Force conversion to float to prevent injection
                    location_in_mesh = [float(x) for x in raw_location]
                except (ValueError, TypeError):
                    location_in_mesh = [0, 0, 0]

            # If objects is empty but 'stl_filename' exists (legacy), construct objects
            if not objects and "stl_filename" in config:
                objects = [{
                    "name": config["stl_filename"],
                    "refinement_level_min": int(config.get("refinement_level", 2)),
                    "refinement_level_max": int(config.get("refinement_level", 2)),
                    "layers": 0
                }]
                # Assume basic global settings
                global_settings = {
                    "castellated_mesh": True,
                    "snap": True,
                    "add_layers": False
                }

            # Security: Sanitize objects list
            safe_objects = []
            for obj in objects:
                safe_obj = obj.copy()
                raw_name = obj.get("name", "")
                if not raw_name:
                    continue

                safe_name = secure_filename(str(raw_name))
                if not safe_name:
                    continue
                safe_obj["name"] = safe_name

                # Validate numeric fields
                try:
                    safe_obj["refinement_level_min"] = int(obj.get("refinement_level_min", 2))
                    safe_obj["refinement_level_max"] = int(obj.get("refinement_level_max", 2))
                    safe_obj["layers"] = int(obj.get("layers", 0))
                except (ValueError, TypeError):
                    safe_obj["refinement_level_min"] = 2
                    safe_obj["refinement_level_max"] = 2
                    safe_obj["layers"] = 0

                safe_objects.append(safe_obj)
            objects = safe_objects

            def get_safe(settings, key, type_func, default):
                try:
                    return type_func(settings.get(key, default))
                except (ValueError, TypeError):
                    return default

            # Extract Global Settings with Defaults
            castellated = "true" if global_settings.get("castellated_mesh", True) else "false"
            snap = "true" if global_settings.get("snap", True) else "false"
            add_layers = "true" if global_settings.get("add_layers", False) else "false"

            # Castellated Controls
            max_global_cells = get_safe(global_settings, "max_global_cells", int, 2000000)
            resolve_feature_angle = get_safe(global_settings, "resolve_feature_angle", int, 30)

            # Snap Controls
            n_smooth_patch = get_safe(global_settings, "n_smooth_patch", int, 3)
            snap_tolerance = get_safe(global_settings, "tolerance", float, 2.0)
            n_solve_iter = get_safe(global_settings, "n_solve_iter", int, 30)
            n_relax_iter = get_safe(global_settings, "n_relax_iter", int, 5)
            # Default to implicit feature snap
            implicit_feature_snap = "true"
            explicit_feature_snap = "false"
            multi_region_feature_snap = "false"

            # Add Layers Controls
            expansion_ratio = get_safe(global_settings, "expansion_ratio", float, 1.0)
            final_layer_thickness = get_safe(global_settings, "final_thickness", float, 0.3)
            min_thickness = get_safe(global_settings, "min_thickness", float, 0.1)
            layer_feature_angle = get_safe(global_settings, "feature_angle", int, 60)

            # Mesh Quality Controls
            max_non_ortho = get_safe(global_settings, "max_non_ortho", int, 65)
            max_boundary_skewness = get_safe(global_settings, "max_boundary_skewness", int, 20)
            max_internal_skewness = get_safe(global_settings, "max_internal_skewness", int, 4)
            min_triangle_twist = get_safe(global_settings, "min_triangle_twist", float, -1)
            relaxed_max_non_ortho = get_safe(global_settings, "relaxed_max_non_ortho", int, 75)

            # Construct Geometry Section
            is_esi = openfoam_version.startswith('v') and len(openfoam_version) >= 5 and openfoam_version[1:5].isdigit()
            
            geometry_str = ""
            for obj in objects:
                name = str(obj["name"])
                if name.lower().endswith(".stl"):
                    if not is_esi:
                        # OpenFOAM Foundation (e.g. 12) requires 'file' keyword
                        geometry_str += f"""
    {name}
    {{
        type triSurfaceMesh;
        file "{name}";
    }}
"""
                    else:
                        # ESI OpenCFD (e.g. v2012)
                        region_name = name
                        geometry_str += f"""
    {name}
    {{
        type triSurfaceMesh;
        name {region_name};
    }}
"""

            # Construct Features Section
            features_str = ""
            for obj in objects:
                name = obj["name"]
                level = obj.get("refinement_level_min", 1)
                features_str += f"""
        {{
            file "{name}";
            level {level};
        }}
"""

            # Construct Refinement Surfaces
            refinement_surfaces_str = ""
            layers_str = ""

            for obj in objects:
                name = obj["name"]
                min_lvl = obj.get("refinement_level_min", 2)
                max_lvl = obj.get("refinement_level_max", 2)
                num_layers = int(obj.get("layers", 0))

                region_name = name

                refinement_surfaces_str += f"""
        {region_name}
        {{
            level ({min_lvl} {max_lvl});
        }}
"""
                if num_layers > 0:
                    layers_str += f"""
        {region_name}
        {{
            nSurfaceLayers {num_layers};
        }}
"""

            # Build the file content
            header_version = f"v{openfoam_version}" if not openfoam_version.startswith('v') else openfoam_version
            header_website = "www.openfoam.com" if is_esi else "www.openfoam.org"
            header_org = "OpenCFD" if is_esi else "The Open Source CFD Toolbox"
            
            content = f"""/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: {header_org}           |
|  \\\\    /   O peration     | Version:  {header_version}                                 |
|   \\\\  /    A nd           | Website:  {header_website}                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      snappyHexMeshDict;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

castellatedMesh {castellated};
snap            {snap};
addLayers       {add_layers};

geometry
{{
{geometry_str}
}};

castellatedMeshControls
{{
    maxGlobalCells {max_global_cells};
    minRefinementCells 0;
    maxLoadUnbalance 0.10;
    nCellsBetweenLevels 3;

    features
    (
{features_str}
    );

    refinementSurfaces
    {{
{refinement_surfaces_str}
    }}

    resolveFeatureAngle {resolve_feature_angle};

    refinementRegions
    {{
    }}

    locationInMesh ({location_in_mesh[0]} {location_in_mesh[1]} {location_in_mesh[2]});

    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch {n_smooth_patch};
    tolerance {snap_tolerance};
    nSolveIter {n_solve_iter};
    nRelaxIter {n_relax_iter};
    nFeatureSnapIter 10;
    implicitFeatureSnap {implicit_feature_snap};
    explicitFeatureSnap {explicit_feature_snap};
    multiRegionFeatureSnap {multi_region_feature_snap};
}}

addLayersControls
{{
    relativeSizes true;
    layers
    {{
{layers_str}
    }}
    expansionRatio {expansion_ratio};
    finalLayerThickness {final_layer_thickness};
    minThickness {min_thickness};
    nGrow 0;
    featureAngle {layer_feature_angle};
    nRelaxIter 3;
    nSmoothSurfaceNormals 1;
    nSmoothNormals 3;
    nSmoothThickness 10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedianAxisAngle 90;
    nBufferCellsNoExtrude 0;
    nLayerIter 50;
}}

meshQualityControls
{{
    maxNonOrtho {max_non_ortho};
    maxBoundarySkewness {max_boundary_skewness};
    maxInternalSkewness {max_internal_skewness};
    maxConcave 80;
    minVol 1e-13;
    minTetQuality 1e-30;
    minArea -1;
    minTwist 0.02;
    minDeterminant 0.001;
    minFaceWeight 0.02;
    minVolRatio 0.01;
    minTriangleTwist {min_triangle_twist};

    nSmoothScale 4;
    errorReduction 0.75;

    relaxed
    {{
        maxNonOrtho {relaxed_max_non_ortho};
    }}
}}

mergeTolerance 1e-6;

// ************************************************************************* //
"""
            with open(dict_path, "w") as f:
                f.write(content)

            logger.info(f"Generated snappyHexMeshDict at {dict_path}")
            return True

        except Exception as e:
            logger.error(f"Error generating snappyHexMeshDict: {e}")
            return False
