from __future__ import annotations

import argparse
from datetime import datetime
from io import StringIO
import socket
import sys
from typing import Any

import pytest

import install
import runtime
from log_paths import dated_log_directory
from runtime import installed_server_port


def test_auto_port_is_reserved_until_installer_releases_it():
    reservation, port = install.reserve_server_port(None, auto_assign=True)
    contender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert 1 <= port <= 65535
        with pytest.raises(OSError):
            contender.bind(("127.0.0.1", port))
    finally:
        contender.close()
        reservation.close()


def test_occupied_explicit_port_reports_actionable_options():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    port = int(occupied.getsockname()[1])
    try:
        with pytest.raises(RuntimeError, match=r"--port PORT.*--auto-port"):
            install.reserve_server_port(port, auto_assign=False)
    finally:
        occupied.close()


def test_installer_port_is_persisted_and_loaded(tmp_path):
    port_file = tmp_path / ".foamtrame-port"
    install.save_server_port(5087, port_file)
    assert installed_server_port(port_file) == 5087


def test_missing_installer_selection_uses_8087(tmp_path):
    assert installed_server_port(tmp_path / "missing-port-file") == 8087


def test_environment_port_overrides_installer_selection(monkeypatch):
    def unexpected_installer_read():
        raise AssertionError("installer port should not be read when env override exists")

    monkeypatch.setattr(runtime, "installed_server_port", unexpected_installer_read)
    settings = runtime.load_runtime_settings({"FOAMTRAME_PORT": "5087"})
    assert settings.default_port == 5087


def test_operational_logs_are_grouped_by_local_calendar_date(tmp_path):
    fixed = datetime(2026, 5, 1, 12, 30)
    assert dated_log_directory(tmp_path / "logs", fixed) == (
        tmp_path / "logs" / "20260501"
    )

    settings = runtime.load_runtime_settings(
        {
            "FOAMTRAME_DATA_DIR": str(tmp_path),
            "FOAMTRAME_LOG_DIR": str(tmp_path / "custom-logs"),
            "FOAMTRAME_PORT": "8087",
        }
    )
    runtime.ensure_runtime_directories(settings)
    assert settings.log_file.name == "foamtrame.log"
    assert settings.log_file.parent.name == datetime.now().strftime("%Y%m%d")
    assert settings.log_file.parent.is_dir()


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_invalid_port_argument_is_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        install.server_port(value)


def test_silent_auto_port_options_are_noninteractive():
    args = install.parse_args(["--silent", "--auto-port"])
    assert args.silent is True
    assert args.auto_port is True
    assert args.port is None


def test_silent_command_disables_prompts_and_redirects_output(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)

    monkeypatch.setattr(install.subprocess, "run", fake_run)
    log = StringIO()
    install.run(["python", "-V"], silent=True, log=log)

    assert captured["stdin"] is install.subprocess.DEVNULL
    assert captured["stdout"] is log
    assert captured["stderr"] is install.subprocess.STDOUT
    assert captured["env"]["UV_NO_PROGRESS"] == "1"
    assert "> python -V" in log.getvalue()


def test_silent_main_completes_without_console_and_persists_port(
    monkeypatch, tmp_path, capsys
):
    class Reservation:
        closed = False

        def close(self):
            self.closed = True

    reservation = Reservation()
    commands: list[tuple[list[str], dict[str, Any]]] = []
    saved_ports: list[int] = []

    def record_run(command: list[str], **kwargs: Any) -> None:
        commands.append((command, kwargs))
    args = argparse.Namespace(
        dev=False,
        silent=True,
        skip_docker_check=True,
        port=None,
        auto_port=True,
    )

    monkeypatch.setattr(install, "parse_args", lambda: args)
    monkeypatch.setattr(
        install,
        "reserve_server_port",
        lambda requested, *, auto_assign: (reservation, 52123),
    )
    monkeypatch.setattr(install, "venv_python", lambda _path: install.Path(sys.executable))
    monkeypatch.setattr(install, "resolve_uv", lambda: install.Path("uv"))
    monkeypatch.setattr(
        install,
        "run",
        record_run,
    )
    monkeypatch.setattr(
        install,
        "save_server_port",
        saved_ports.append,
    )
    monkeypatch.setattr(install, "INSTALL_LOG", tmp_path / "logs" / "install.log")

    assert install.main() == 0
    assert reservation.closed is True
    assert saved_ports == [52123]
    assert commands
    sync_command, sync_options = commands[0]
    assert sync_command[:3] == ["uv", "sync", "--locked"]
    assert "--no-dev" in sync_command
    assert sync_options["env"]["UV_PYTHON_DOWNLOADS"] == "never"
    assert all(kwargs["silent"] is True for _, kwargs in commands)
    assert capsys.readouterr() == ("", "")
