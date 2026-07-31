"""trame_vtk_slicer module for FOAMFlask.

Provides high-performance interactive post-processing visualizers
using Trame and VTK, powered by TrameVisualizer in postprocessor.py.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from backend.post.postprocessor import TrameVisualizer

logger = logging.getLogger("FOAMFlask")


class SliceVisualizer:
    """Adapter class delegating slice requests to TrameVisualizer."""

    def __init__(self):
        self._visualizer = TrameVisualizer()

    def process(self, case_path: str, params: Dict[str, Any], parent_id: Optional[str] = None) -> Dict[str, Any]:
        target_file = self._resolve_target_file(case_path)
        if not target_file:
            return {"status": "error", "message": "No suitable VTK or mesh file found"}

        params = dict(params or {})
        params["operation"] = "Slice"
        return self._visualizer.start_visualization(target_file, params)

    def _resolve_target_file(self, path_str: str) -> Optional[str]:
        return self._visualizer._resolve_target_file(path_str)


class IsosurfaceVisualizer:
    """Adapter class delegating isosurface / contour requests to TrameVisualizer."""

    _instance: Optional[IsosurfaceVisualizer] = None

    def __init__(self):
        self._visualizer = TrameVisualizer()

    @classmethod
    def get_instance(cls) -> IsosurfaceVisualizer:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start_visualization(self, case_or_file_path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        target_file = self._resolve_target_file(case_or_file_path)
        if not target_file:
            return {"status": "error", "message": "No suitable VTK or mesh file found"}

        params = dict(params or {})
        params.setdefault("operation", "Slice")
        return self._visualizer.start_visualization(target_file, params)

    def stop_visualization(self) -> None:
        self._visualizer.stop_visualization()

    def _resolve_target_file(self, path_str: str) -> Optional[str]:
        return self._visualizer._resolve_target_file(path_str)

    def load_mesh(self, file_path: str) -> Dict[str, Any]:
        """Simple metadata extractor for mesh loading compatibility."""
        import pyvista as pv
        try:
            mesh = pv.read(file_path)
            if isinstance(mesh, pv.MultiBlock):
                mesh = mesh.combine()
            point_arrays = list(mesh.point_data.keys())
            cell_arrays = list(mesh.cell_data.keys())
            return {
                "status": "success",
                "file_path": file_path,
                "n_points": mesh.n_points,
                "n_cells": mesh.n_cells,
                "point_arrays": point_arrays,
                "cell_arrays": cell_arrays,
                "bounds": list(mesh.bounds)
            }
        except Exception as e:
            logger.error(f"Error reading mesh metadata in IsosurfaceVisualizer: {e}")
            return {"status": "error", "message": str(e), "point_arrays": []}

    def get_scalar_field_info(self) -> Dict[str, Any]:
        return {}


# Global instance for backward compatibility
isosurface_visualizer = IsosurfaceVisualizer.get_instance()
VisualizationManager = IsosurfaceVisualizer


class StreamlineVisualizer:
    """Adapter class delegating streamline requests to TrameVisualizer."""

    def __init__(self):
        self._visualizer = TrameVisualizer()

    def process(self, case_path: str, params: Dict[str, Any], parent_id: Optional[str] = None) -> Dict[str, Any]:
        params = dict(params or {})
        params["operation"] = "Streamlines"
        return self._visualizer.start_visualization(case_path, params)


class SurfaceProjectionVisualizer:
    """Adapter class delegating surface projection requests to TrameVisualizer."""

    def __init__(self):
        self._visualizer = TrameVisualizer()

    def process(self, case_path: str, params: Dict[str, Any], parent_id: Optional[str] = None) -> Dict[str, Any]:
        params = dict(params or {})
        params["operation"] = "Slice"
        return self._visualizer.start_visualization(case_path, params)
