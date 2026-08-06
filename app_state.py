from __future__ import annotations

import copy
import json
import logging
import threading
from pathlib import Path
from typing import Any

from database import SCHEMA_VERSION, database
from runtime import settings

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


def default_app_state() -> dict[str, Any]:
    return {
        "version": APP_STATE_VERSION,
        "case_config": default_case_config(),
        "run_history": [],
    }


def _normalise_app_state(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("App state must be a JSON object.")

    config = data.get("case_config", {})
    history = data.get("run_history", [])
    if not isinstance(config, dict):
        raise ValueError("case_config must be a JSON object.")
    if not isinstance(history, list) or not all(isinstance(item, dict) for item in history):
        raise ValueError("run_history must be a JSON array of objects.")

    normalised_config = default_case_config()
    for key in normalised_config:
        if key in config:
            value = config[key]
            normalised_config[key] = "" if value is None else str(value)

    return {
        "version": APP_STATE_VERSION,
        "case_config": normalised_config,
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
