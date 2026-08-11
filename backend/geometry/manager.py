import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Union
from werkzeug.utils import secure_filename
from backend.utils import sanitize_error

logger = logging.getLogger("FOAMTrame")

class GeometryManager:
    """Manages geometry files (STL) in the OpenFOAM case."""

    @staticmethod
    def upload_stl(case_path: Union[str, Path], file, filename: str) -> Dict[str, Union[bool, str]]:
        """
        Save an uploaded STL file to the constant/triSurface directory.

        Args:
            case_path: Path to the case directory.
            file: File object from the request.
            filename: Name of the file.

        Returns:
            Dictionary with success status and message.
        """
        try:
            path = Path(case_path).resolve()
            tri_surface_dir = path / "constant" / "triSurface"
            tri_surface_dir.mkdir(parents=True, exist_ok=True)

            safe_filename = secure_filename(filename)
            if not safe_filename:
                return {"success": False, "message": "Invalid filename."}

            # Security: Strict extension validation
            # ⚡ Bolt Optimization: Use tuple and str.endswith for faster extension validation
            allowed_extensions = (".stl", ".obj", ".gz")
            # Check the final extension
            if not safe_filename.lower().endswith(allowed_extensions):
                 return {"success": False, "message": "Only .stl, .obj, and .gz files are allowed."}

            filepath = tri_surface_dir / safe_filename
            file.save(str(filepath))

            logger.info(f"Uploaded Geometry to {filepath}")
            return {"success": True, "message": "File uploaded successfully.", "filename": safe_filename}

        except Exception as e:
            logger.error(f"Error uploading Geometry: {e}")
            return {"success": False, "message": sanitize_error(e)}

    @staticmethod
    def list_stls(case_path: Union[str, Path]) -> Dict[str, Union[bool, List[Dict[str, Union[str, int]]], str]]:
        """
        List all geometry files in the constant/triSurface directory.

        Args:
            case_path: Path to the case directory.

        Returns:
            Dictionary with success status and list of dicts with 'name' and 'size'.
        """
        try:
            path = Path(case_path).resolve()
            tri_surface_dir = path / "constant" / "triSurface"

            # List .stl, .obj, and .gz files
            # ⚡ Bolt Optimization: Use os.scandir instead of Path.iterdir()
            # Significantly faster for directories with many files
            files = []
            allowed_extensions = {".stl", ".obj", ".gz"}
            allowed_ext_tuple = tuple(allowed_extensions)

            try:
                with os.scandir(str(tri_surface_dir)) as entries:
                    for entry in entries:
                        if entry.is_file():
                            # Check extension efficiently
                            name = entry.name
                            if name.lower().endswith(allowed_ext_tuple):
                                files.append({
                                    "name": name,
                                    "size": entry.stat().st_size
                                })
            except FileNotFoundError:
                return {"success": True, "files": []}
            except OSError:
                pass # Directory might have been deleted concurrently

            # Sort by name
            files.sort(key=lambda x: x["name"])
            return {"success": True, "files": files}

        except Exception as e:
            logger.error(f"Error listing STLs: {e}")
            return {"success": False, "message": sanitize_error(e)}

    @staticmethod
    def delete_stl(case_path: Union[str, Path], filename: str) -> Dict[str, Union[bool, str]]:
        """
        Delete an STL file from the constant/triSurface directory.

        Args:
            case_path: Path to the case directory.
            filename: Name of the file to delete.

        Returns:
            Dictionary with success status and message.
        """
        try:
            path = Path(case_path).resolve()
            filepath = path / "constant" / "triSurface" / secure_filename(filename)

            # ⚡ Bolt Optimization: Use EAFP to avoid redundant Path.exists() check
            try:
                os.remove(filepath)
            except FileNotFoundError:
                return {"success": False, "message": "File not found."}
            logger.info(f"Deleted STL {filepath}")
            return {"success": True, "message": "File deleted successfully."}

        except Exception as e:
            logger.error(f"Error deleting STL: {e}")
            return {"success": False, "message": sanitize_error(e)}
