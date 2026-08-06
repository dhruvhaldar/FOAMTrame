from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent


def _env_path(env: Mapping[str, str], key: str, default: Path) -> Path:
    value = env.get(key, "").strip()
    return Path(value).expanduser().resolve() if value else default.resolve()


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key, "").strip()
    if not value:
        return default
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise ValueError(f"{key} must be between 1 and 65535.")
    return parsed


@dataclass(frozen=True)
class RuntimeSettings:
    project_root: Path
    data_dir: Path
    log_dir: Path
    database_path: Path
    default_port: int
    log_level: str

    @property
    def log_file(self) -> Path:
        return self.log_dir / "foamtrame.log"


def load_runtime_settings(env: Mapping[str, str] | None = None) -> RuntimeSettings:
    values = os.environ if env is None else env
    data_dir = _env_path(values, "FOAMTRAME_DATA_DIR", PROJECT_ROOT)
    log_dir = _env_path(values, "FOAMTRAME_LOG_DIR", data_dir / "logs")
    database_path = _env_path(
        values, "FOAMTRAME_DATABASE_PATH", data_dir / "foamtrame.db"
    )
    log_level = values.get("FOAMTRAME_LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("FOAMTRAME_LOG_LEVEL is not a valid Python logging level.")
    return RuntimeSettings(
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        log_dir=log_dir,
        database_path=database_path,
        default_port=_env_int(values, "FOAMTRAME_PORT", 8087),
        log_level=log_level,
    )


settings = load_runtime_settings()


def ensure_runtime_directories(config: RuntimeSettings = settings) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    config.database_path.parent.mkdir(parents=True, exist_ok=True)


def configure_logging(config: RuntimeSettings = settings) -> None:
    """Configure console and bounded file logging once per process."""
    root = logging.getLogger()
    if getattr(root, "_foamtrame_configured", False):
        return

    ensure_runtime_directories(config)
    level = getattr(logging, config.log_level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)

    rotating_file = logging.handlers.RotatingFileHandler(
        config.log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    rotating_file.setFormatter(formatter)
    rotating_file.setLevel(level)

    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(rotating_file)
    root._foamtrame_configured = True  # type: ignore[attr-defined]


def run_preflight(
    config: RuntimeSettings = settings, *, check_docker: bool = True
) -> dict[str, Any]:
    """Return machine-readable installation/runtime diagnostics."""
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    python_ok = sys.version_info >= (3, 10)
    add(
        "python",
        "pass" if python_ok else "fail",
        f"{platform.python_implementation()} {platform.python_version()}",
    )

    try:
        ensure_runtime_directories(config)
        with tempfile.NamedTemporaryFile(dir=config.data_dir, delete=True):
            pass
        add("data_directory", "pass", str(config.data_dir))
    except Exception as exc:
        add("data_directory", "fail", str(exc))

    sqlite_ok = sqlite3.sqlite_version_info >= (3, 35, 0)
    add(
        "sqlite",
        "pass" if sqlite_ok else "fail",
        sqlite3.sqlite_version,
    )

    docker_executable = shutil.which("docker")
    if not check_docker:
        add("docker_cli", "skip", "Docker check disabled")
        add("docker_daemon", "skip", "Docker check disabled")
    elif docker_executable:
        add("docker_cli", "pass", docker_executable)
        try:
            result = subprocess.run(
                [docker_executable, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                add("docker_daemon", "pass", result.stdout.strip() or "reachable")
            else:
                detail = result.stderr.strip() or result.stdout.strip() or "not reachable"
                add("docker_daemon", "warn", detail)
        except (OSError, subprocess.SubprocessError) as exc:
            add("docker_daemon", "warn", str(exc))
    else:
        add("docker_cli", "warn", "Docker executable was not found in PATH")
        add("docker_daemon", "skip", "Docker CLI unavailable")

    failed = [item for item in checks if item["status"] == "fail"]
    return {
        "ok": not failed,
        "platform": platform.platform(),
        "settings": {
            "data_dir": str(config.data_dir),
            "log_file": str(config.log_file),
            "database_path": str(config.database_path),
            "default_port": config.default_port,
        },
        "checks": checks,
    }


def format_preflight(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2)
