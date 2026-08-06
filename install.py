from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MINIMUM_PYTHON = (3, 10)


def venv_python(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an isolated FOAMTrame installation on Windows or Linux."
    )
    parser.add_argument(
        "--venv",
        default=".venv",
        help="Virtual-environment directory relative to the project (default: .venv)",
    )
    parser.add_argument("--dev", action="store_true", help="Install test dependencies")
    parser.add_argument(
        "--no-upgrade-tools",
        action="store_true",
        help="Do not upgrade pip, setuptools, and wheel",
    )
    parser.add_argument(
        "--skip-docker-check",
        action="store_true",
        help="Skip the Docker executable check during final diagnostics",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        raise SystemExit(f"FOAMTrame requires Python {required} or newer.")

    venv_dir = (PROJECT_ROOT / args.venv).resolve()
    python = venv_python(venv_dir)
    if not python.exists():
        run([sys.executable, "-m", "venv", str(venv_dir)])

    if not python.exists():
        raise SystemExit(f"Virtual environment was not created correctly: {venv_dir}")

    if not args.no_upgrade_tools:
        run([str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    run([str(python), "-m", "pip", "install", "-r", str(PROJECT_ROOT / "requirements.txt")])
    if args.dev:
        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(PROJECT_ROOT / "requirements-dev.txt"),
            ]
        )

    run([str(python), str(PROJECT_ROOT / "manage.py"), "init-db"])
    doctor = [str(python), str(PROJECT_ROOT / "manage.py"), "doctor"]
    if args.skip_docker_check:
        doctor.append("--skip-docker")
    run(doctor)

    if platform.system() != "Windows":
        for script in ("install.sh", "start.sh"):
            try:
                (PROJECT_ROOT / script).chmod(0o755)
            except OSError:
                pass

    docker = shutil.which("docker")
    print("\nFOAMTrame installation completed successfully.")
    if not docker and not args.skip_docker_check:
        print("Docker was not found. Install/start Docker before running OpenFOAM operations.")
    if platform.system() == "Windows":
        print(r"Start with: .\start.ps1")
    else:
        print("Start with: ./start.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
