"""Validated local case lifecycle operations, called under an idle-case guard."""

import re
import shutil
import stat
import tempfile
import uuid
from pathlib import Path


def case_destination(root: Path, name: str) -> Path:
    """Resolve a new immediate child without accepting redirects or overwrites."""
    root = root.resolve(strict=True)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) or name.endswith(
        "."
    ):
        raise ValueError(
            "Use 1–128 letters, numbers, underscores, dots or hyphens; start with a letter or number."
        )
    if name.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raise ValueError("This name is reserved by Windows.")
    target = root / name
    if target.exists() or target.is_symlink() or target.resolve() != target:
        raise ValueError("A case or another entry with that name already exists.")
    return target


def case_source(root: Path, name: str) -> Path:
    root = root.resolve(strict=True)
    path = root / name
    if (
        not name
        or name.startswith(".")
        or Path(name).name != name
        or path.resolve() != path
        or path.parent != root
    ):
        raise ValueError("Select a case directly inside the configured case workspace.")
    if (
        not path.is_dir()
        or not (path / "system").is_dir()
        or not (path / "constant").is_dir()
    ):
        raise ValueError("The selected directory is not an OpenFOAM case.")
    return path


def _reject_links(path: Path) -> None:
    info = path.lstat()
    if (
        path.is_symlink()
        or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise ValueError(
            "Case operations do not follow symbolic links or directory junctions."
        )
    if path.is_dir():
        for child in path.iterdir():
            _reject_links(child)


def manage_case(root: Path, name: str, action: str, new_name: str = "") -> Path:
    """Copy/rename a case, or recoverably remove it to workspace-local trash."""
    source = case_source(root, name)
    root = source.parent
    if action not in {"copy", "rename", "delete"}:
        raise ValueError("Unknown case operation.")
    _reject_links(source)
    if action == "delete":
        trash = root / ".foamtrame-trash"
        if trash.resolve() != trash or trash.is_symlink():
            raise ValueError("Trash must remain inside the case workspace.")
        trash.mkdir(exist_ok=True)
        target = trash / f"{uuid.uuid4().hex}-{source.name}"
        source.rename(target)
        return target
    target = case_destination(root, new_name)
    if action == "rename":
        source.rename(target)
        return target
    staging = Path(tempfile.mkdtemp(prefix=".foamtrame-copy-", dir=root))
    try:
        shutil.copytree(source, staging / "case", symlinks=True)  # nosec: validated case to unique staging; never follows links
        _reject_links(staging / "case")
        # Recheck after a potentially lengthy copy, before publishing the case.
        case_destination(root, new_name)
        (staging / "case").rename(target)
    finally:
        if staging.resolve().parent != root or not staging.name.startswith(
            ".foamtrame-copy-"
        ):
            raise ValueError("Unsafe staging cleanup path.")
        shutil.rmtree(staging)  # nosec: verified unique staging directory inside workspace
    return target
