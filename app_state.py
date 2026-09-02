from __future__ import annotations

import copy
import io
import json
import logging
import shutil
import stat
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from database import SCHEMA_VERSION, database
from runtime import settings
from security import default_security_preferences, normalise_security_preferences

logger = logging.getLogger("FOAMTrame")

LEGACY_APP_STATE_FILE = settings.data_dir / "app_state.json"
LEGACY_CONFIG_FILE = settings.data_dir / "case_config.json"
LEGACY_RUN_HISTORY_FILE = settings.data_dir / "run_history.json"
APP_STATE_VERSION = SCHEMA_VERSION
DEEP_BACKUP_FORMAT = "foamtrame-deep-copy"
DEEP_BACKUP_VERSION = 1
DEEP_BACKUP_MANIFEST = "foamtrame-backup.json"
DEEP_BACKUP_STATE = "app_state.json"
MAX_DEEP_BACKUP_FILES = 100_000
MAX_DEEP_BACKUP_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024

_state_lock = threading.RLock()


def default_case_config() -> dict[str, str]:
    return {
        "CASE_ROOT": str((settings.data_dir / "tutorial_cases").resolve()),
        "DOCKER_IMAGE": "haldardhruv/ubuntu_noble_openfoam:v12",
        "OPENFOAM_VERSION": "12",
        "ACTIVE_CASE": "",
    }


def default_plot_preferences() -> dict[str, str]:
    return {
        "font": "helvetica_neue",
        "background": "glass",
        "logo_mode": "none",
        "custom_logo_data": "",
    }


def default_geometry_preferences() -> dict[str, Any]:
    return {
        "preferred_mode": "case",
        "library_selection": "",
        "case_geometry_selections": {},
    }


def default_app_state() -> dict[str, Any]:
    return {
        "version": APP_STATE_VERSION,
        "case_config": default_case_config(),
        "plot_preferences": default_plot_preferences(),
        "geometry_preferences": default_geometry_preferences(),
        "security_preferences": default_security_preferences(),
        "run_history": [],
    }


def _normalise_app_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("App state must be a JSON object.")

    config = data.get("case_config", {})
    plot_preferences = data.get("plot_preferences", {})
    geometry_preferences = data.get("geometry_preferences", {})
    security_preferences = data.get("security_preferences", {})
    history = data.get("run_history", [])
    if not isinstance(config, dict):
        raise ValueError("case_config must be a JSON object.")
    if not isinstance(history, list) or not all(
        isinstance(item, dict) for item in history
    ):
        raise ValueError("run_history must be a JSON array of objects.")
    if not isinstance(plot_preferences, dict):
        raise ValueError("plot_preferences must be a JSON object.")
    if not isinstance(geometry_preferences, dict):
        raise ValueError("geometry_preferences must be a JSON object.")
    if not isinstance(security_preferences, dict):
        raise ValueError("security_preferences must be a JSON object.")

    normalised_config = default_case_config()
    for key in normalised_config:
        if key in config:
            value = config[key]
            normalised_config[key] = "" if value is None else str(value)

    normalised_plots = default_plot_preferences()
    for key in normalised_plots:
        if key in plot_preferences:
            value = plot_preferences[key]
            normalised_plots[key] = "" if value is None else str(value)

    if normalised_plots["font"] not in {
        "helvetica_neue",
        "roboto",
        "times_new_roman",
        "arial",
    }:
        normalised_plots["font"] = "helvetica_neue"
    if normalised_plots["background"] not in {"glass", "white", "black", "grey"}:
        normalised_plots["background"] = "glass"
    if normalised_plots["logo_mode"] not in {"none", "foamflask", "custom"}:
        normalised_plots["logo_mode"] = "none"
    if len(normalised_plots["custom_logo_data"]) > 3_000_000:
        normalised_plots["custom_logo_data"] = ""
        normalised_plots["logo_mode"] = "none"

    normalised_geometry = default_geometry_preferences()
    for key in ("preferred_mode", "library_selection"):
        if key in geometry_preferences:
            value = geometry_preferences[key]
            normalised_geometry[key] = "" if value is None else str(value)
    if normalised_geometry["preferred_mode"] not in {"case", "custom", "library"}:
        normalised_geometry["preferred_mode"] = "case"
    selection = normalised_geometry["library_selection"]
    if len(selection) > 255 or selection != Path(selection).name:
        normalised_geometry["library_selection"] = ""
    case_selections = geometry_preferences.get("case_geometry_selections", {})
    if isinstance(case_selections, dict):
        for raw_case, raw_selection in list(case_selections.items())[:100]:
            case_name = str(raw_case)
            geometry_selection = "" if raw_selection is None else str(raw_selection)
            selection_path = PurePosixPath(geometry_selection)
            if (
                case_name
                and len(case_name) <= 255
                and Path(case_name).name == case_name
                and len(geometry_selection) <= 512
                and not selection_path.is_absolute()
                and ".." not in selection_path.parts
            ):
                normalised_geometry["case_geometry_selections"][case_name] = (
                    geometry_selection
                )

    return {
        "version": APP_STATE_VERSION,
        "case_config": normalised_config,
        "plot_preferences": normalised_plots,
        "geometry_preferences": normalised_geometry,
        "security_preferences": normalise_security_preferences(security_preferences),
        "run_history": copy.deepcopy(history[:100]),
    }


def _migrate_legacy_state() -> dict[str, Any]:
    migrated = default_app_state()

    if LEGACY_APP_STATE_FILE.exists():
        try:
            with LEGACY_APP_STATE_FILE.open("r", encoding="utf-8") as stream:
                return _normalise_app_state(json.load(stream))
        except Exception as exc:
            logger.warning("Could not migrate legacy app state: %s", exc)

    if LEGACY_CONFIG_FILE.exists():
        try:
            with LEGACY_CONFIG_FILE.open("r", encoding="utf-8") as stream:
                legacy_config = json.load(stream)
            if isinstance(legacy_config, dict):
                migrated["case_config"].update(legacy_config)
        except Exception as exc:
            logger.warning("Could not migrate legacy case config: %s", exc)

    if LEGACY_RUN_HISTORY_FILE.exists():
        try:
            with LEGACY_RUN_HISTORY_FILE.open("r", encoding="utf-8") as stream:
                legacy_history = json.load(stream)
            if isinstance(legacy_history, list):
                migrated["run_history"] = legacy_history[:100]
        except Exception as exc:
            logger.warning("Could not migrate legacy run history: %s", exc)

    return _normalise_app_state(migrated)


def load_app_state() -> dict[str, Any]:
    with _state_lock:
        try:
            if not database.has_app_state():
                migrated = _migrate_legacy_state()
                database.save_app_state(migrated)
                logger.info("Migrated application state to %s", database.path)
            return _normalise_app_state(database.load_app_state())
        except Exception as exc:
            logger.error("Failed to load app state: %s", exc)
            return default_app_state()


def save_app_state(data: dict[str, Any]) -> bool:
    with _state_lock:
        try:
            database.save_app_state(_normalise_app_state(data))
            return True
        except Exception as exc:
            logger.error("Failed to save app state: %s", exc)
            return False


def load_case_config() -> dict[str, str]:
    return copy.deepcopy(load_app_state()["case_config"])


def update_case_config(updates: dict[str, Any]) -> bool:
    with _state_lock:
        data = load_app_state()
        data["case_config"].update(updates)
        return save_app_state(data)


def load_plot_preferences() -> dict[str, str]:
    return copy.deepcopy(load_app_state()["plot_preferences"])


def load_geometry_preferences() -> dict[str, Any]:
    return copy.deepcopy(load_app_state()["geometry_preferences"])


def update_plot_preferences(updates: dict[str, Any]) -> bool:
    with _state_lock:
        data = load_app_state()
        data["plot_preferences"].update(updates)
        return save_app_state(data)


def update_geometry_preferences(updates: dict[str, Any]) -> bool:
    with _state_lock:
        data = load_app_state()
        data["geometry_preferences"].update(updates)
        return save_app_state(data)


def load_security_preferences() -> dict[str, Any]:
    return copy.deepcopy(load_app_state()["security_preferences"])


def update_security_preferences(updates: dict[str, Any]) -> bool:
    with _state_lock:
        data = load_app_state()
        data["security_preferences"].update(updates)
        return save_app_state(data)


def load_run_history() -> list[dict[str, Any]]:
    return copy.deepcopy(load_app_state()["run_history"])


def update_run_history(history: list[dict[str, Any]]) -> bool:
    with _state_lock:
        data = load_app_state()
        data["run_history"] = history[:100]
        return save_app_state(data)


def export_app_state_json() -> str:
    return json.dumps(load_app_state(), indent=2) + "\n"


def restore_app_state_json(payload: str | bytes) -> dict[str, Any]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    try:
        restored = _normalise_app_state(json.loads(payload))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc.msg} (line {exc.lineno})") from exc

    if not save_app_state(restored):
        raise OSError("The restored app state could not be saved.")
    return copy.deepcopy(restored)


def export_deep_copy(case_root: str | Path | None = None) -> bytes:
    """Return a ZIP containing app state and every case in the case workspace."""
    state = load_app_state()
    source_root = Path(case_root or state["case_config"]["CASE_ROOT"]).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Case workspace does not exist: {source_root}")
    manifest = {
        "format": DEEP_BACKUP_FORMAT,
        "format_version": DEEP_BACKUP_VERSION,
        "state_file": DEEP_BACKUP_STATE,
        "cases_directory": "cases",
    }

    output = io.BytesIO()
    with zipfile.ZipFile(
        output, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        archive.writestr(DEEP_BACKUP_MANIFEST, json.dumps(manifest, indent=2) + "\n")
        archive.writestr(DEEP_BACKUP_STATE, json.dumps(state, indent=2) + "\n")
        for case_path in sorted(source_root.iterdir(), key=lambda path: path.name):
            if not case_path.is_dir() or case_path.is_symlink():
                continue
            archive.writestr(f"cases/{case_path.name}/", b"")
            for path in sorted(case_path.rglob("*")):
                if path.is_symlink():
                    logger.warning("Skipping symlink from deep copy: %s", path)
                    continue
                relative = path.relative_to(source_root).as_posix()
                archive_name = f"cases/{relative}"
                if path.is_dir():
                    archive.writestr(f"{archive_name}/", b"")
                elif path.is_file():
                    archive.write(path, archive_name)
    return output.getvalue()


def _validated_deep_copy_members(
    archive: zipfile.ZipFile,
) -> tuple[dict[str, Any], list[zipfile.ZipInfo], set[str]]:
    infos = archive.infolist()
    if len(infos) > MAX_DEEP_BACKUP_FILES:
        raise ValueError("The deep-copy archive contains too many files.")
    if sum(info.file_size for info in infos) > MAX_DEEP_BACKUP_UNCOMPRESSED_BYTES:
        raise ValueError("The expanded deep-copy archive exceeds the 4 GB limit.")
    names = archive.namelist()
    if names.count(DEEP_BACKUP_MANIFEST) != 1:
        raise ValueError("This ZIP is not a FOAMTrame deep-copy backup.")
    if names.count(DEEP_BACKUP_STATE) != 1:
        raise ValueError("The deep-copy archive must contain one app_state.json.")

    try:
        manifest = json.loads(archive.read(DEEP_BACKUP_MANIFEST))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("The deep-copy manifest is not valid JSON.") from exc
    if not isinstance(manifest, dict) or (
        manifest.get("format") != DEEP_BACKUP_FORMAT
        or manifest.get("format_version") != DEEP_BACKUP_VERSION
        or manifest.get("state_file") != DEEP_BACKUP_STATE
    ):
        raise ValueError("The deep-copy manifest format is not supported.")

    members: list[zipfile.ZipInfo] = []
    case_names: set[str] = set()
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        if name in {DEEP_BACKUP_MANIFEST, DEEP_BACKUP_STATE}:
            continue
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or len(path.parts) < 2
            or path.parts[0] != "cases"
            or not path.parts[1]
        ):
            raise ValueError(f"Unsafe deep-copy archive path: {name}")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f"Deep-copy archives cannot contain symlinks: {name}")
        if len(path.parts) == 2 and not info.is_dir():
            raise ValueError(f"A case archive root must be a directory: {name}")
        canonical_name = path.as_posix().rstrip("/").casefold()
        if canonical_name in seen:
            raise ValueError(f"Duplicate deep-copy archive path: {name}")
        seen.add(canonical_name)
        case_names.add(path.parts[1])
        members.append(info)
    return manifest, members, case_names


def validate_deep_copy(payload: bytes) -> int:
    """Validate a deep-copy ZIP and return its number of case directories."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("The selected file is not a valid ZIP archive.") from exc
    with archive:
        _, _, case_names = _validated_deep_copy_members(archive)
        try:
            _normalise_app_state(json.loads(archive.read(DEEP_BACKUP_STATE)))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("The deep-copy app state is not valid JSON.") from exc
    return len(case_names)


def restore_deep_copy(payload: bytes, destination_root: str | Path) -> dict[str, Any]:
    """Restore cases from a deep-copy ZIP without overwriting local cases."""
    destination = Path(destination_root).resolve()
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("The selected file is not a valid ZIP archive.") from exc

    with archive:
        _, members, case_names = _validated_deep_copy_members(archive)
        try:
            restored = _normalise_app_state(json.loads(archive.read(DEEP_BACKUP_STATE)))
        except KeyError as exc:
            raise ValueError(
                "The deep-copy archive is missing app_state.json."
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("The deep-copy app state is not valid JSON.") from exc

        collisions = sorted(
            name for name in case_names if (destination / name).exists()
        )
        if collisions:
            names = ", ".join(collisions[:5])
            suffix = "…" if len(collisions) > 5 else ""
            raise FileExistsError(
                f"Restore would overwrite existing case(s): {names}{suffix}. "
                "Choose an empty case workspace in Advanced Settings first."
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        moved: list[Path] = []
        with tempfile.TemporaryDirectory(
            prefix=".foamtrame-restore-", dir=destination.parent
        ) as temporary:
            staging_root = Path(temporary)
            for info in members:
                relative = PurePosixPath(info.filename).relative_to("cases")
                target = staging_root.joinpath(*relative.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)

            destination.mkdir(parents=True, exist_ok=True)
            try:
                for case_name in sorted(case_names):
                    target = destination / case_name
                    shutil.move(str(staging_root / case_name), str(target))
                    moved.append(target)
                restored["case_config"]["CASE_ROOT"] = str(destination)
                if not save_app_state(restored):
                    raise OSError("The restored app state could not be saved.")
            except Exception:
                for target in reversed(moved):
                    if target.is_dir():
                        shutil.rmtree(target)
                raise
    return copy.deepcopy(restored)
