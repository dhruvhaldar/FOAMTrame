from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON_VERSION = "3.12.13"
PYTHON_ARCHIVES = {
    "cpython-3.12.13+20260807-x86_64-pc-windows-msvc-install_only_stripped.tar.gz": (
        "18bcc65b17921806b72cdc88bcf000bf67a2c99a8fc381fe1629f2b9ba56858d"
    ),
    "cpython-3.12.13+20260807-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz": (
        "506191be3ee7bd190a8834dcdc1b3bc70aab50608deccc711935aa007239cabd"
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.mark.parametrize("archive_name,expected_hash", PYTHON_ARCHIVES.items())
def test_vendored_python_archives_match_published_checksums(
    archive_name, expected_hash
):
    archive = PROJECT_ROOT / "vendor" / "python" / PYTHON_VERSION / archive_name
    checksum = archive.with_name(f"{archive.name}.sha256")
    assert archive.is_file()
    assert checksum.read_text(encoding="utf-8").split()[0] == expected_hash
    assert sha256_file(archive) == expected_hash


def run_bootstrap(tools_dir: Path, *, force: bool, path: str | None = None) -> Path:
    environment = os.environ.copy()
    environment["FOAMTRAME_TOOLS_DIR"] = str(tools_dir)
    if force:
        environment["FOAMTRAME_FORCE_BUNDLED_PYTHON"] = "1"
    else:
        environment.pop("FOAMTRAME_FORCE_BUNDLED_PYTHON", None)
    if path is not None:
        environment["PATH"] = path

    if platform.system() == "Windows":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "python_bootstrap.ps1"),
        ]
    else:
        command = ["bash", str(PROJECT_ROOT / "python_bootstrap.sh")]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


@pytest.mark.skipif(
    platform.system() not in {"Windows", "Linux"},
    reason="Bundled Python targets Windows and Linux",
)
def test_bundled_python_is_isolated_and_compatible_python_on_path_is_preferred(
    tmp_path,
):
    bundled_tools = tmp_path / "bundled-tools"
    bundled_python = run_bootstrap(bundled_tools, force=True)
    version = subprocess.run(
        [str(bundled_python), "-c", "import sys; print(*sys.version_info[:3])"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert version.stdout.strip() == "3 12 13"
    assert bundled_python.is_relative_to(bundled_tools)

    unused_tools = tmp_path / "must-remain-absent"
    path_entries = [str(bundled_python.parent)]
    if platform.system() == "Windows":
        alias_dir = tmp_path / "later-alias"
        alias_dir.mkdir()
        (alias_dir / "python3.cmd").write_text(
            "@echo C:\\decoy\\python.exe\n", encoding="utf-8"
        )
        path_entries.append(str(alias_dir))
    path_entries.append(os.environ["PATH"])
    preferred_path = os.pathsep.join(path_entries)
    selected_python = run_bootstrap(
        unused_tools,
        force=False,
        path=preferred_path,
    )
    assert selected_python.resolve() == bundled_python.resolve()
    assert not unused_tools.exists()
