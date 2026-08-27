from __future__ import annotations

import copy
import json
import logging
import threading
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
