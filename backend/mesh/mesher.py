"""PyVista handler module for mesh visualization in FOAMTrame.

This module provides functionality to load and visualize VTK/VTP mesh files using PyVista.
It includes features for generating screenshots, interactive HTML viewers, and managing
mesh data for visualization purposes.
"""

import base64
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

from cachebox import LRUCache
import pyvista as pv
from pyvista import DataSet, Plotter
import PIL.Image

from backend.visualization.base import BaseVisualizer

logger = logging.getLogger("FOAMTrame")

class MeshVisualizer(BaseVisualizer):
    """Handles mesh visualization using PyVista with in-memory caching.

    Attributes:
        mesh: The currently loaded mesh data.
        plotter: The active PyVista plotter instance.
    """

    def __init__(self) -> None:
        """Initialize the mesh visualizer."""
        super().__init__() # Initialize base with default extensions
        self.mesh: Optional[DataSet] = None
        self.plotter: Optional[Plotter] = None
        self.current_mesh_path: Optional[str] = None
        self.current_mesh_mtime: Optional[float] = None
        # ⚡ Bolt Optimization: Cache decimated meshes to avoid re-computation
        self._decimated_cache: Dict[int, DataSet] = {}
        # ⚡ Bolt Optimization: Cache screenshots (LRU)
        self._screenshot_cache = LRUCache(maxsize=32)
        # ⚡ Bolt Optimization: Cache interactive HTML (LRU)
        self._html_cache = LRUCache(maxsize=16)

    def __del__(self) -> None:
        """Clean up resources by closing the plotter if it exists."""
        if self.plotter is not None:
            self.plotter.close()

    def load_mesh(
        self, file_path: Union[str, Path], for_contour: bool = False, **kwargs: Any
    ) -> Dict[str, Any]:
        """Load a mesh from a VTK/VTP file.

        Args:
            file_path: Path to the VTK/VTP file.
            for_contour: Whether the mesh is being loaded for contour generation.
            **kwargs: Additional arguments for future extension.

        Returns:
            Dictionary containing mesh information.
        """
        try:
            path = self.validate_file(file_path)
            if not path:
                raise FileNotFoundError(f"Mesh file not found or invalid: {file_path}")

            path_str = str(path)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                raise FileNotFoundError(f"Mesh file not found or invalid: {file_path}")

            # ⚡ Bolt Optimization: Cache Check
            if (
                self.mesh is not None
                and self.current_mesh_path == path_str
                and self.current_mesh_mtime == mtime
            ):
                logger.info(f"[FOAMTrame] [mesher] Using cached mesh for {path_str}")
            else:
                logger.info(f"[FOAMTrame] [mesher] Loading mesh from {path_str}")

                # Use BaseVisualizer's safe loader
                self.mesh = self.load_mesh_safe(path)
                if self.mesh is None:
                     raise RuntimeError("Failed to load mesh data")

                self.current_mesh_path = path_str
                self.current_mesh_mtime = mtime
                # ⚡ Bolt Optimization: Clear decimated cache on new mesh load (tied to self.mesh)
                self._decimated_cache.clear()
                # ⚡ Bolt Optimization: Do NOT clear HTML cache (persists across meshes)
                # self._html_cache.clear()

                logger.info(
                    f"[FOAMTrame] [mesher] Loaded mesh: {self.mesh.n_points} points, {self.mesh.n_cells} cells"
                )

            # Get mesh information
            mesh_info = {
                "n_points": self.mesh.n_points,
                "n_cells": self.mesh.n_cells,
                "bounds": [float(x) for x in self.mesh.bounds],
                "center": self.mesh.center,
                "length": self.mesh.length,
                "volume": self.mesh.volume if hasattr(self.mesh, "volume") else None,
                "array_names": self.mesh.array_names,
                "point_arrays": list(self.mesh.point_data.keys()),
                "cell_arrays": list(self.mesh.cell_data.keys()),
                "success": True,
            }

            return mesh_info

        except Exception as e:
            logger.error(f"Error loading mesh: {e}")
            return {"success": False, "error": str(e)}

    def get_mesh_screenshot(
        self,
        file_path: Union[str, Path],
        width: int = 800,
        height: int = 600,
        show_edges: bool = True,
        color: str = "lightblue",
        camera_position: Optional[str] = None,
    ) -> Optional[str]:
        """Generate a screenshot of the mesh."""
        try:
            # Security: Limit dimensions
            MAX_DIMENSION = 4096
            if width > MAX_DIMENSION or height > MAX_DIMENSION:
                logger.error(f"Screenshot dimensions exceed limit ({MAX_DIMENSION}px): {width}x{height}")
                return None

            path = self.validate_file(file_path)
            if not path:
                return None

            try:
                mtime = path.stat().st_mtime
            except OSError:
                return None

            # ⚡ Bolt Optimization: Check screenshot cache
            h_color = tuple(color) if isinstance(color, list) else color
            h_cam = tuple(camera_position) if isinstance(camera_position, list) else camera_position

            cache_key = (str(path), mtime, width, height, show_edges, h_color, h_cam)

            if cache_key in self._screenshot_cache:
                logger.debug(f"[FOAMTrame] Serving cached screenshot for {path}")
                return self._screenshot_cache[cache_key]

            # Load mesh (uses caching)
            mesh_info = self.load_mesh(path)
            if not mesh_info.get("success"):
                return None

            # Create plotter
            plotter = pv.Plotter(off_screen=True, window_size=[width, height])
            plotter.add_mesh(self.mesh, color=color, show_edges=show_edges)
            plotter.add_axes()

            if camera_position:
                if camera_position == "xy": plotter.view_xy()
                elif camera_position == "xz": plotter.view_xz()
                elif camera_position == "yz": plotter.view_yz()
                elif camera_position == "iso": plotter.view_isometric()
            else:
                plotter.reset_camera()

            # Render
            img_bytes = plotter.screenshot(return_img=True, transparent_background=False)
            plotter.close()

            # Convert to base64
            buffered = BytesIO()
            PIL.Image.fromarray(img_bytes).save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            # Update cache
            self._screenshot_cache[cache_key] = img_str

            return img_str

        except Exception as e:
            logger.error(f"Error generating screenshot: {e}")
            return None

    def get_interactive_viewer_html(
        self, file_path: Union[str, Path], show_edges: bool = True, color: str = "lightblue"
    ) -> Optional[str]:
        """Generate a fully interactive HTML viewer with enhanced controls."""
        try:
            # ⚡ Bolt Optimization: Check cache first to avoid expensive load_mesh (disk I/O + parsing)
            # Validate path and get mtime without loading the full mesh
            path = self.validate_file(file_path)
            if not path:
                return None

            path_str = str(path)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                return None

            cache_key = (path_str, mtime, show_edges, color)

            if cache_key in self._html_cache:
                logger.debug(f"[FOAMTrame] Serving cached HTML for {path_str}")
                return self._html_cache[cache_key]

            # Cache miss: Load mesh and generate
            mesh_info = self.load_mesh(path)
            if not mesh_info.get("success"):
                return None

            # ⚡ Bolt Optimization: Decimate mesh for web performance
            # Use shared decimation logic
            target_faces = 200000

            # Check decimated cache
            if target_faces in self._decimated_cache:
                display_mesh = self._decimated_cache[target_faces]
            else:
                display_mesh = self.decimate_mesh(self.mesh, target_faces=target_faces)
                self._decimated_cache[target_faces] = display_mesh

            # Use base class to generate HTML
            # Note: Base class generates HTML file then reads it.
            html_content = self.generate_html_content(
                mesh=display_mesh,
                color=color,
                opacity=1.0,
                show_edges=show_edges,
                window_size=[1200, 800]
            )

            # Store in cache
            if html_content:
                self._html_cache[cache_key] = html_content

            return html_content

        except Exception as e:
            logger.error(f"Error generating interactive viewer: {e}")
            return None

    def get_available_meshes(
        self, case_dir: Union[str, Path], tutorial: str
    ) -> List[Dict[str, Union[str, int]]]:
        """Get list of available mesh files in the case directory."""
        # This logic is specific to Mesh scanning, so we keep it here unless we want to move it to base
        # It's not strictly "visualization", it's "file listing".
        # I'll keep it here as per plan "only interactive code" refactoring.
        try:
            tutorial_path = Path(case_dir) / tutorial
            if not tutorial_path.exists():
                return []

            tutorial_path_str = str(tutorial_path)
            if not tutorial_path_str.endswith(os.sep):
                tutorial_path_str += os.sep
            tutorial_path_len = len(tutorial_path_str)

            mesh_files = []
            seen_paths = set()
            # Extensions handled by base class
            ext_tuple = tuple(self.allowed_extensions)

            def _scan(path_str: str):
                try:
                    subdirs_to_visit = []
                    with os.scandir(path_str) as entries:
                        for entry in entries:
                            if entry.is_dir(follow_symlinks=False):
                                name = entry.name
                                if name.startswith("."): continue
                                try:
                                    float(name)
                                    continue
                                except ValueError:
                                    if name == "system": continue
                                subdirs_to_visit.append(entry.path)

                            elif entry.is_file(follow_symlinks=True):
                                name = entry.name
                                if name.endswith(ext_tuple):
                                    entry_path = entry.path
                                    if entry_path in seen_paths: continue
                                    seen_paths.add(entry_path)

                                    try:
                                        if entry_path.startswith(tutorial_path_str):
                                            rel_path_str = entry_path[tutorial_path_len:]
                                        else:
                                            rel_path_str = str(Path(entry_path).relative_to(tutorial_path))

                                        mesh_files.append({
                                            "name": name,
                                            "path": entry_path,
                                            "relative_path": rel_path_str,
                                            # "size": entry.stat().st_size,
                                        })
                                    except (ValueError, OSError):
                                        continue
                    for subdir in subdirs_to_visit:
                        _scan(subdir)
                except OSError:
                    pass

            _scan(str(tutorial_path))
            return mesh_files

        except Exception as e:
            logger.error(f"Error getting available meshes: {e}")
            return []

# Global instance for use as a singleton
mesh_visualizer = MeshVisualizer()
