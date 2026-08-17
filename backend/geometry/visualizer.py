import logging
import pyvista as pv
from pathlib import Path
from typing import Optional, Union, Dict, Any
import multiprocessing
import tempfile
import os
import shutil
import hashlib
import stat
import random
from cachebox import LRUCache
from backend.visualization.base import BaseVisualizer

logger = logging.getLogger("FOAMTrame")

# ⚡ Bolt Optimization: Cache for mesh info
# Stores (path, mtime) -> mesh_info_dict
_MESH_INFO_CACHE = LRUCache(maxsize=100)

def _get_cache_dir() -> Path:
    """Get the cache directory, creating it if it doesn't exist."""
    cache_dir = Path(tempfile.gettempdir()) / "FOAMTrame_geometry_cache"

    # Security: Ensure directory exists with secure permissions (0700)
    # ⚡ Bolt Optimization: Use EAFP to avoid redundant Path.exists() check
    try:
        cache_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        # If mkdir fails (e.g. race condition), check permissions below
        pass

    # Ensure permissions are set (mkdir mode might be ignored or modified by umask)
    # We do this always to ensure security even if directory already existed
    try:
        os.chmod(cache_dir, 0o700)
    except OSError as e:
        # If we can't chmod (e.g. not owner), we'll catch it in the ownership check below
        logger.debug(f"Security: Failed to set permissions on cache dir: {e}")

    # Check permissions and ownership
    try:
        st = cache_dir.stat()

        # Check if owned by current user (POSIX only)
        if hasattr(os, "getuid"):
            if st.st_uid != os.getuid():
                logger.warning(
                    f"Security: Cache directory {cache_dir} is not owned by current user. "
                    "Using a temporary directory instead."
                )
                return Path(tempfile.mkdtemp(prefix="FOAMTrame_geo_"))

        # Check permissions (rwx------) (POSIX only)
        if os.name == "posix":
            if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                logger.warning(
                    f"Security: Cache directory {cache_dir} has insecure permissions. "
                    "Attempting to fix."
                )
                try:
                    os.chmod(cache_dir, 0o700)
                except OSError as e:
                    logger.warning(f"Security: Failed to fix permissions: {e}")
                    return Path(tempfile.mkdtemp(prefix="FOAMTrame_geo_"))
    except OSError as e:
        logger.warning(f"Security: Error checking cache dir permissions: {e}")
        return Path(tempfile.mkdtemp(prefix="FOAMTrame_geo_"))

    return cache_dir

CACHE_SIZE_LIMIT_MB = 500  # Limit cache to 500MB

def _cleanup_cache():
    """
    Maintain cache size within limits by deleting oldest files.
    """
    try:
        # ⚡ Bolt Optimization: Probabilistic cleanup
        if random.random() > 0.1:
            return

        cache_dir = _get_cache_dir()
        limit_bytes = CACHE_SIZE_LIMIT_MB * 1024 * 1024

        files = []
        total_size = 0

        try:
            with os.scandir(str(cache_dir)) as entries:
                for entry in entries:
                    if entry.is_file():
                        stat = entry.stat()
                        total_size += stat.st_size
                        files.append((entry.path, stat.st_mtime, stat.st_size))
        except OSError:
            return

        if total_size > limit_bytes:
            files.sort(key=lambda x: x[1])

            for path, _, size in files:
                try:
                    os.unlink(path)
                    total_size -= size
                    if total_size <= limit_bytes:
                        break
                except OSError:
                    pass
    except Exception as e:
        logger.warning(f"Error during cache cleanup: {e}")

def _generate_html_process(file_path: str, output_path: str, color: str, opacity: float, optimize: bool):
    """
    Helper function to be run in a separate process to generate the HTML.
    Uses BaseVisualizer logic.
    """
    try:
        # Use BaseVisualizer instance for logic re-use
        # Since this is a separate process, we instantiate a lightweight version
        viz = BaseVisualizer()

        mesh = viz.load_mesh_safe(file_path)
        if mesh is None:
            raise Exception("Failed to load mesh")

        # Decimate
        TARGET_FACES = 50000 if optimize else 100000
        mesh = viz.decimate_mesh(mesh, target_faces=TARGET_FACES, optimize=optimize)

        # Use PyVista directly here to write to specific output_path provided by parent
        # BaseVisualizer.generate_html_content uses temp file, we want control here
        plotter = pv.Plotter(notebook=False, off_screen=True)
        plotter.add_mesh(mesh, color=color, opacity=opacity, show_edges=False)
        plotter.show_grid()
        plotter.show_axes()
        plotter.camera_position = 'iso'
        plotter.export_html(output_path)
        plotter.close()

    except Exception as e:
        print(f"Error in subprocess: {e}")
        try:
            os.remove(output_path)
        except OSError:
            pass

class GeometryVisualizer(BaseVisualizer):
    """Visualizes geometry files (STL) using PyVista with caching and multiprocessing."""

    def __init__(self):
        super().__init__() # Use default extensions

    def get_interactive_html(self, file_path: Union[str, Path], color: str = "lightblue", opacity: float = 1.0, optimize: bool = False) -> Optional[str]:
        """
        Generates an interactive HTML representation of the STL file.
        Uses multiprocessing for robustness.
        """
        try:
            path = self.validate_file(file_path)
            if not path:
                return None

            # ⚡ Bolt Optimization: Caching
            try:
                mtime = path.stat().st_mtime
            except OSError:
                return None

            try:
                cache_key_str = f"{str(path)}_{mtime}_{color}_{opacity}_{optimize}"
                cache_key = hashlib.sha256(cache_key_str.encode()).hexdigest()

                cache_dir = _get_cache_dir()
                cache_path = cache_dir / f"{cache_key}.html"

                # ⚡ Bolt Optimization: EAFP pattern for cache read avoids double syscall
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        logger.debug(f"Serving geometry from cache: {cache_path}")
                        return f.read()
                except FileNotFoundError:
                    pass
            except Exception as e:
                logger.warning(f"Cache check failed: {e}")

            # Create a temp file for the output
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
                temp_output_path = tmp.name

            # Run generation in a separate process
            p = multiprocessing.Process(
                target=_generate_html_process,
                args=(str(path), temp_output_path, color, opacity, optimize)
            )
            p.start()
            p.join(timeout=120)

            if p.is_alive():
                p.terminate()
                p.join()
                logger.error("HTML generation timed out")
                try:
                    os.remove(temp_output_path)
                except OSError:
                    pass
                return None

            if p.exitcode != 0:
                logger.error("HTML generation process failed")
                try:
                    os.remove(temp_output_path)
                except OSError:
                    pass
                return None

            try:
                if os.path.getsize(temp_output_path) == 0:
                     logger.error("HTML output file is empty")
                     try:
                        os.remove(temp_output_path)
                     except OSError:
                        pass
                     return None
            except OSError:
                 logger.error("HTML output file is missing")
                 return None

            with open(temp_output_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # ⚡ Bolt Optimization: Save to cache
            try:
                _cleanup_cache()
                shutil.move(temp_output_path, cache_path)
            except Exception as e:
                logger.warning(f"Failed to save to cache: {e}")
                try:
                    os.remove(temp_output_path)
                except OSError:
                    pass

            return html_content

        except Exception as e:
            logger.error(f"Error generating interactive geometry view: {e}")
            return None

    def get_mesh_info(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Get basic information about the mesh (bounds, center, etc.)."""
        try:
            path = self.validate_file(file_path)
            if not path:
                return {"success": False, "error": "Invalid file"}

            try:
                mtime = path.stat().st_mtime
            except OSError:
                return {"success": False, "error": "Failed to load mesh"}

            # ⚡ Bolt Optimization: Check in-memory cache
            try:
                cache_key = (str(path), mtime)
                if cache_key in _MESH_INFO_CACHE:
                    return _MESH_INFO_CACHE[cache_key]
            except Exception:
                pass

            mesh = self.load_mesh_safe(path)
            if mesh is None:
                return {"success": False, "error": "Failed to load mesh"}

            result = {
                "success": True,
                "bounds": list(mesh.bounds),
                "center": list(mesh.center),
                "n_points": mesh.n_points,
                "n_cells": mesh.n_cells
            }

            try:
                _MESH_INFO_CACHE[cache_key] = result
            except Exception:
                pass

            return result

        except Exception as e:
            logger.error(f"Error getting mesh info: {e}")
            return {"success": False, "error": str(e)}

# Global instance for use as a singleton
# Note: In previous code it wasn't a singleton explicitly, but just a class with static methods
# or an instance. Here we provide an instance to match expected usage if any.
# However, the methods were static in original. I made them instance methods to use 'self' and inheritance.
# So I should export an instance.
geometry_visualizer = GeometryVisualizer()
