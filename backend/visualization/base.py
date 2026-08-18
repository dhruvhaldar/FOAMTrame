"""Base class for visualization handlers using PyVista.

This module provides a common base class for geometry and mesh visualizers,
encapsulating shared logic for file handling, decompression, mesh decimation,
and HTML export.
"""

import logging
import os
import tempfile
import gzip
from pathlib import Path
from typing import Optional, Union, List
import pyvista as pv
from backend.utils import safe_decompress

logger = logging.getLogger("FOAMTrame")


class BaseVisualizer:
    """Base class for PyVista-based visualizers.

    Attributes:
        allowed_extensions (set): Set of allowed file extensions.
    """

    def __init__(self, allowed_extensions: Optional[set] = None):
        """Initialize the base visualizer.

        Args:
            allowed_extensions (set, optional): Set of allowed file extensions.
                Defaults to common mesh formats if None.
        """
        if allowed_extensions is None:
            self.allowed_extensions = {
                ".stl",
                ".obj",
                ".obj.gz",
                ".stl.gz",
                ".ply",
                ".vtp",
                ".vtu",
                ".g",
                ".vtk",
            }
        else:
            self.allowed_extensions = allowed_extensions

    def validate_file(self, file_path: Union[str, Path]) -> Optional[Path]:
        """Validate file path and extension.

        Args:
            file_path: Path to the file.

        Returns:
            Resolved Path object if valid, None otherwise.
        """
        try:
            path = Path(file_path).resolve()

            # Security check: Ensure file extension is allowed
            suffixes = path.suffixes
            # Handle multi-part extensions like .obj.gz and .stl.gz
            if len(suffixes) >= 2:
                combined_ext = suffixes[-2] + suffixes[-1]
                if combined_ext in {".obj.gz", ".stl.gz"}:
                    ext = combined_ext
                else:
                    ext = path.suffix.lower()
            else:
                ext = path.suffix.lower()

            if ext not in self.allowed_extensions:
                logger.error(f"Security: Invalid file extension: {ext}")
                return None

            return path
        except Exception as e:
            logger.error(f"Error validating file: {e}")
            return None

    def load_mesh_safe(self, file_path: Union[str, Path]) -> Optional[pv.DataSet]:
        """Load a mesh safely, handling gzip if necessary.

        Args:
            file_path: Path to the mesh file.

        Returns:
            PyVista DataSet or None on error.
        """
        temp_read_path = None
        try:
            path = Path(file_path)
            read_path_str = str(path)

            if read_path_str.lower().endswith(".gz"):
                # Determine suffix for temp file (e.g. .obj for .obj.gz)
                suffixes = path.suffixes
                if len(suffixes) >= 2:
                    suffix = suffixes[-2]
                else:
                    suffix = ".vtk"  # Default fallback

                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    temp_read_path = tmp.name
                    with gzip.open(read_path_str, "rb") as f_in:
                        safe_decompress(f_in, tmp)
                    read_path_str = temp_read_path

            # ⚡ Bolt Optimization: Disable progress bar
            mesh = pv.read(read_path_str, progress_bar=False)
            return mesh

        except Exception as e:
            logger.error(f"Error loading mesh {file_path}: {e}")
            return None
        finally:
            if temp_read_path:
                try:
                    os.remove(temp_read_path)
                except OSError:
                    pass

    def decimate_mesh(
        self, mesh: pv.DataSet, target_faces: int = 100000, optimize: bool = False
    ) -> pv.DataSet:
        """Decimate mesh to reduce size for web visualization.

        Args:
            mesh: The PyVista DataSet to decimate.
            target_faces: Target number of faces.
            optimize: Whether aggressive optimization is requested.

        Returns:
            Decimated mesh.
        """
        if optimize:
            target_faces = int(target_faces * 0.5)

        if mesh.n_cells <= target_faces:
            return mesh

        try:
            # We need PolyData for decimation
            if not isinstance(mesh, pv.PolyData):
                # Extract surface geometry
                mesh_poly = mesh.extract_surface()
            else:
                mesh_poly = mesh

            # Calculate reduction factor (0.0 to 1.0)
            if mesh_poly.n_cells > target_faces:
                reduction = 1.0 - (target_faces / mesh_poly.n_cells)
                # Ensure reduction is valid
                reduction = max(0.0, min(0.95, reduction))

                logger.info(
                    f"Decimating mesh from {mesh_poly.n_cells} to ~{target_faces} cells (reduction={reduction:.2f})"
                )

                # ⚡ Bolt Optimization: Use fast decimate_pro if available (topology preserving, faster)
                if hasattr(mesh_poly, "decimate_pro"):
                    try:
                        mesh_poly = mesh_poly.decimate_pro(
                            reduction, preserve_topology=True
                        )
                    except Exception as e:
                        logger.warning(
                            f"decimate_pro failed ({e}), falling back to standard decimate"
                        )
                        mesh_poly = mesh_poly.decimate(reduction)
                else:
                    mesh_poly = mesh_poly.decimate(reduction)

            return mesh_poly
        except Exception as e:
            logger.warning(f"Mesh decimation failed: {e}")
            return mesh

    def generate_html_content(
        self,
        mesh: pv.DataSet,
        color: str = "lightblue",
        opacity: float = 1.0,
        show_edges: bool = False,
        window_size: Optional[List[int]] = None,
    ) -> Optional[str]:
        """Generate HTML content for interactive viewer using PyVista.

        Args:
            mesh: The mesh to visualize.
            color: Mesh color.
            opacity: Mesh opacity.
            show_edges: Whether to show edges.
            window_size: Window size [width, height].

        Returns:
            HTML string or None on error.
        """
        plotter = None
        try:
            # Create a temporary file for the output
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
                temp_output_path = tmp.name

            plotter = pv.Plotter(
                notebook=False, off_screen=True, window_size=window_size or [1024, 768]
            )
            plotter.add_mesh(
                mesh,
                color=color,
                opacity=opacity,
                show_edges=show_edges,
                smooth_shading=True,
            )
            plotter.show_grid()
            plotter.show_axes()
            plotter.camera_position = "iso"

            # Export
            plotter.export_html(temp_output_path)

            try:
                if os.path.getsize(temp_output_path) == 0:
                    logger.error("HTML output file is empty")
                    return None
            except OSError:
                logger.error("HTML output file is missing")
                return None

            with open(temp_output_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            return html_content

        except Exception as e:
            logger.error(f"Error generating HTML content: {e}")
            return None
        finally:
            if plotter is not None:
                plotter.close()
            if "temp_output_path" in locals():
                try:
                    os.remove(temp_output_path)
                except OSError:
                    pass
