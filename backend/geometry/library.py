from __future__ import annotations

import platform
import re
import os
from pathlib import Path
from typing import Any


LIBRARY_EXTENSIONS = (".stl", ".obj", ".ply", ".stl.gz", ".obj.gz", ".ply.gz")
_SAFE_LIBRARY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,254}")


def is_supported_geometry_name(name: str) -> bool:
    """Return whether *name* is a safe, renderable library filename."""
    return (
        bool(_SAFE_LIBRARY_NAME.fullmatch(name))
        and Path(name).name == name
        and name.lower().endswith(LIBRARY_EXTENSIONS)
    )


def resolve_case_path(case_root: str | Path, case_name: str) -> Path:
    """Resolve a direct child case without allowing traversal outside its root."""
    root = Path(case_root).resolve()
    if not case_name or Path(case_name).name != case_name:
        raise ValueError("Select a valid active case.")
    case_path = (root / case_name).resolve()
    if case_path.parent != root:
        raise ValueError("The active case is outside the configured case root.")
    return case_path


def _files_under(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    resolved_directory = directory.resolve()

    def is_inside_directory(path: Path) -> bool:
        try:
            path.resolve().relative_to(resolved_directory)
            return True
        except ValueError:
            return False

    return sorted(
        (
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.name.lower().endswith(LIBRARY_EXTENSIONS)
            and is_inside_directory(path)
        ),
        key=lambda path: path.relative_to(directory).as_posix().lower(),
    )


def list_case_geometry_choices(
    case_root: str | Path, case_name: str
) -> dict[str, list[Path]]:
    """Return default and individually selectable triSurface geometries.

    The empty key represents the case's default geometry. Native
    ``constant/geometry`` files define that default when present; otherwise all
    supported ``constant/triSurface`` files do. Each triSurface file is also an
    individual choice so imported library geometry can be selected explicitly.
    """
    constant = resolve_case_path(case_root, case_name) / "constant"
    geometry_files = _files_under(constant / "geometry")
    tri_surface = constant / "triSurface"
    tri_surface_files = _files_under(tri_surface)
    default_files = geometry_files or tri_surface_files
    choices: dict[str, list[Path]] = {"": default_files}
    for path in tri_surface_files:
        choices[path.relative_to(tri_surface).as_posix()] = [path]
    return choices


def list_case_geometry(case_root: str | Path, case_name: str) -> list[Path]:
    """List the default renderable geometry belonging to an OpenFOAM case."""
    return list_case_geometry_choices(case_root, case_name)[""]


_OPENFOAM_BASHRC = r"""
requested="$1"
bashrc="/opt/openfoam${requested}/etc/bashrc"
if [ ! -f "$bashrc" ]; then
    bashrc="$(find /opt -maxdepth 4 -type f -path '*/etc/bashrc' 2>/dev/null | head -n 1)"
fi
[ -n "$bashrc" ] && [ -f "$bashrc" ] || exit 2
source "$bashrc" >/dev/null 2>&1 || exit 3
geometry_dir="${FOAM_TUTORIALS}/resources/geometry"
[ -d "$geometry_dir" ] || exit 4
"""


def list_resource_geometry(
    docker_client: Any,
    docker_image: str,
    openfoam_version: str,
) -> list[str]:
    """List geometry resources from the configured OpenFOAM image."""
    if docker_client is None:
        raise RuntimeError("Docker is unavailable.")
    shell_script = (
        _OPENFOAM_BASHRC
        + r"""
find "$geometry_dir" -maxdepth 1 -type f -printf '%f\n'
"""
    )
    output = docker_client.containers.run(
        docker_image,
        [
            "bash",
            "-c",
            shell_script,
            "list_resource_geometry",
            str(openfoam_version),
        ],
        remove=True,
        stdout=True,
        stderr=False,
        network_disabled=True,
    )
    names = {
        line.strip()
        for line in output.decode("utf-8", errors="replace").splitlines()
        if is_supported_geometry_name(line.strip())
    }
    return sorted(names, key=str.lower)


def import_resource_geometry(
    docker_client: Any,
    docker_image: str,
    openfoam_version: str,
    case_root: str | Path,
    case_name: str,
    filename: str,
) -> Path:
    """Copy one validated image resource into the active case triSurface folder."""
    if docker_client is None:
        raise RuntimeError("Docker is unavailable.")
    if not is_supported_geometry_name(filename):
        raise ValueError("Select a valid OpenFOAM geometry resource.")

    tri_surface = resolve_case_path(case_root, case_name) / "constant" / "triSurface"
    tri_surface.mkdir(parents=True, exist_ok=True)
    imported = tri_surface / filename
    if imported.is_symlink():
        raise ValueError("The selected destination is an unsafe symbolic link.")
    host_path = (
        tri_surface.as_posix() if platform.system() == "Windows" else str(tri_surface)
    )
    shell_script = (
        _OPENFOAM_BASHRC
        + r"""
cp -- "$geometry_dir/$2" /output/
"""
    )
    run_options: dict[str, Any] = {
        "remove": True,
        "stdout": True,
        "stderr": True,
        "network_disabled": True,
        "volumes": {host_path: {"bind": "/output", "mode": "rw"}},
    }
    if platform.system() != "Windows" and hasattr(os, "getuid"):
        run_options["user"] = f"{os.getuid()}:{os.getgid()}"
    docker_client.containers.run(
        docker_image,
        [
            "bash",
            "-c",
            shell_script,
            "import_resource_geometry",
            str(openfoam_version),
            filename,
        ],
        **run_options,
    )
    if not imported.is_file():
        raise RuntimeError("The image did not copy the selected geometry file.")
    return imported
