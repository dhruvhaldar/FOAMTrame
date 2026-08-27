from __future__ import annotations

import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

from log_paths import dated_log_directory
from uv_bootstrap import resolve_uv

PROJECT_ROOT = Path(__file__).resolve().parent
MINIMUM_PYTHON = (3, 10)
DEFAULT_SERVER_PORT = 8087
PORT_FILE = PROJECT_ROOT / ".foamtrame-port"
INSTALL_LOG = dated_log_directory(PROJECT_ROOT / "logs") / "install.log"


def server_port(value: str) -> int:
    """Parse and validate a TCP port supplied on the installer command line."""
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def reserve_server_port(
    requested_port: int | None,
    *,
    auto_assign: bool,
) -> tuple[socket.socket, int]:
    """Reserve the selected loopback port for the duration of installation."""
    port = 0 if auto_assign else (requested_port or DEFAULT_SERVER_PORT)
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        reservation.bind(("127.0.0.1", port))
    except OSError as exc:
        reservation.close()
        display_port = requested_port or DEFAULT_SERVER_PORT
        raise RuntimeError(
            f"Port {display_port} is not available. Specify a different port with "
            "--port PORT or let FOAMTrame select one with --auto-port."
        ) from exc
    return reservation, int(reservation.getsockname()[1])


def save_server_port(port: int, path: Path = PORT_FILE) -> None:
    """Persist the installer-selected port without introducing another JSON file."""
    path.write_text(f"{port}\n", encoding="utf-8")


def venv_python(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def installer_environment(
    *, silent: bool, base: dict[str, str] | None = None
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    if silent:
        environment.update(
            {
                "CI": "1",
                "PYTHONUNBUFFERED": "1",
                "UV_NO_PROGRESS": "1",
            }
        )
    return environment


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    silent: bool = False,
    log: TextIO | None = None,
) -> None:
    command_line = " ".join(command)
    if silent:
        if log is None:
            raise ValueError("Silent installer commands require an installation log.")
        log.write(f"\n> {command_line}\n")
        log.flush()
        subprocess.run(  # nosec: argv list is assembled from trusted installer paths
            command,
            cwd=PROJECT_ROOT,
            env=installer_environment(silent=True, base=env),
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return

    print(f"\n> {command_line}", flush=True)
    subprocess.run(  # nosec: argv list is assembled from trusted installer paths
        command, cwd=PROJECT_ROOT, env=env, check=True
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an isolated FOAMTrame installation on Windows or Linux."
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Install development and test dependencies",
    )
    parser.add_argument(
        "--silent",
        "--quiet",
        "-q",
        action="store_true",
        help=(
            "Run unattended without console progress; write command output to "
            "logs/YYYYMMDD/install.log"
        ),
    )
    parser.add_argument(
        "--skip-docker-check",
        action="store_true",
        help="Skip the Docker executable check during final diagnostics",
    )
    port_group = parser.add_mutually_exclusive_group()
    port_group.add_argument(
        "--port",
        type=server_port,
        help=f"Trame server port (default when omitted: {DEFAULT_SERVER_PORT})",
    )
    port_group.add_argument(
        "--auto-port",
        action="store_true",
        help="Automatically select and persist an available loopback port",
    )
    return parser.parse_args(argv)


def open_install_log(selected_port: int, args: argparse.Namespace) -> TextIO:
    INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = INSTALL_LOG.open("a", encoding="utf-8", buffering=1)
    log.write("\n" + "=" * 80 + "\n")
    log.write(f"FOAMTrame silent install {datetime.now().astimezone().isoformat()}\n")
    log.write(f"Python: {sys.executable}\n")
    log.write(f"Platform: {platform.platform()}\n")
    log.write(f"Selected port: {selected_port}\n")
    log.write(f"Development dependencies: {args.dev}\n")
    return log


def main() -> int:
    args = parse_args()
    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        raise SystemExit(f"FOAMTrame requires Python {required} or newer.")

    try:
        port_reservation, selected_port = reserve_server_port(
            args.port,
            auto_assign=args.auto_port,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    if not args.silent:
        print(
            f"FOAMTrame will use http://127.0.0.1:{selected_port}/ "
            f"({'automatically selected' if args.auto_port else 'validated and reserved'}).",
            flush=True,
        )

    install_log = open_install_log(selected_port, args) if args.silent else None
    try:
        try:
            uv = resolve_uv()
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc

        venv_dir = PROJECT_ROOT / ".venv"
        sync_environment = installer_environment(silent=args.silent)
        sync_environment["UV_PYTHON_DOWNLOADS"] = "never"
        sync_command = [
            str(uv),
            "sync",
            "--locked",
            "--python",
            sys.executable,
        ]
        if not args.dev:
            sync_command.append("--no-dev")
        run(
            sync_command,
            env=sync_environment,
            silent=args.silent,
            log=install_log,
        )

        python = venv_python(venv_dir)
        if not python.exists():
            raise SystemExit(
                f"Virtual environment was not created correctly: {venv_dir}"
            )

        run(
            [str(python), str(PROJECT_ROOT / "manage.py"), "init-db"],
            silent=args.silent,
            log=install_log,
        )
        doctor = [str(python), str(PROJECT_ROOT / "manage.py"), "doctor"]
        if args.skip_docker_check:
            doctor.append("--skip-docker")
        doctor_env = installer_environment(silent=args.silent)
        doctor_env["FOAMTRAME_PORT"] = str(selected_port)
        run(
            doctor,
            env=doctor_env,
            silent=args.silent,
            log=install_log,
        )

        if platform.system() != "Windows":
            for script in ("install.sh", "start.sh"):
                try:
                    (PROJECT_ROOT / script).chmod(0o755)
                except OSError:
                    pass

        save_server_port(selected_port)
    except subprocess.CalledProcessError as exc:
        if args.silent:
            print(
                f"FOAMTrame silent installation failed (exit {exc.returncode}). "
                f"See {INSTALL_LOG}.",
                file=sys.stderr,
            )
            return exc.returncode or 1
        raise
    finally:
        port_reservation.close()
        if install_log is not None:
            install_log.close()

    docker = shutil.which("docker")
    if args.silent:
        return 0
    print("\nFOAMTrame installation completed successfully.")
    print(f"Server URL: http://127.0.0.1:{selected_port}/")
    if not docker and not args.skip_docker_check:
        print(
            "Docker was not found. Install/start Docker before running OpenFOAM operations."
        )
    if platform.system() == "Windows":
        print(r"Start with: .\start.ps1")
    else:
        print("Start with: ./start.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
