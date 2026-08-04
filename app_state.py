from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("FOAMTrame")

APP_STATE_FILE = Path("app_state.json")
LEGACY_CONFIG_FILE = Path("case_config.json")
LEGACY_RUN_HISTORY_FILE = Path("run_history.json")
APP_STATE_VERSION = 1

_state_lock = threading.RLock()


def default_case_config() -> dict[str, str]:
    return {
        "CASE_ROOT": str(Path("tutorial_cases").resolve()),
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


def _atomic_write(data: dict[str, Any]) -> None:
    target = APP_STATE_FILE.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.stem}-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temp_path = Path(stream.name)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _migrate_legacy_state() -> dict[str, Any]:
    migrated = default_app_state()

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

    migrated = _normalise_app_state(migrated)
    _atomic_write(migrated)

    # The consolidated file is safely on disk, so legacy state can no longer
    # diverge from the source of truth.
    LEGACY_CONFIG_FILE.unlink(missing_ok=True)
    LEGACY_RUN_HISTORY_FILE.unlink(missing_ok=True)
    return migrated


def load_app_state() -> dict[str, Any]:
    with _state_lock:
        if not APP_STATE_FILE.exists():
            return copy.deepcopy(_migrate_legacy_state())
        try:
            with APP_STATE_FILE.open("r", encoding="utf-8") as stream:
                return _normalise_app_state(json.load(stream))
        except Exception as exc:
            logger.error("Failed to load app state: %s", exc)
            return default_app_state()


def save_app_state(data: dict[str, Any]) -> bool:
    with _state_lock:
        try:
            _atomic_write(_normalise_app_state(data))
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
