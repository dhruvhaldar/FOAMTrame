"""Exercise real Git archives, extraction, checksums and local-state exclusion."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import zipfile

import pytest

from scripts.build_distribution import PLATFORMS, build_distribution


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "source with spaces"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    for name, content in {
        "app.py": "print('application')\n",
        "static/icons/logo.svg": "<svg/>\n",
        "uv.lock": "version = 1\n",
        "start.sh": "#!/bin/sh\n",
        "install.ps1": "# installer\n",
        "vendor/runtime.bin": "bundled runtime\n",
    }.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "Fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


@pytest.mark.parametrize("platform", PLATFORMS)
def test_archive_round_trip_and_checksum(
    repository: Path, tmp_path: Path, platform: str
):
    archive = build_distribution(platform, tmp_path / "release output", root=repository)
    assert platform in archive.name
    digest, filename = archive.with_suffix(".zip.sha256").read_text().split()
    assert filename == archive.name
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    destination = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        assert all(name.startswith("FOAMTrame/") for name in package.namelist())
        package.extractall(destination)
    for source in repository.rglob("*"):
        if source.is_file() and ".git" not in source.relative_to(repository).parts:
            assert (
                destination / "FOAMTrame" / source.relative_to(repository)
            ).read_bytes() == source.read_bytes()


def test_archive_excludes_untracked_state_and_uncommitted_changes(
    repository: Path, tmp_path: Path
):
    for name in ("foamtrame.db", ".env", ".foamtrame-port", "case-results.dat"):
        (repository / name).write_text("private local state", encoding="utf-8")
    (repository / "app.py").write_text("uncommitted edit", encoding="utf-8")
    archive = build_distribution(PLATFORMS[0], tmp_path / "output", root=repository)
    with zipfile.ZipFile(archive) as package:
        assert package.read("FOAMTrame/app.py").decode().splitlines() == [
            "print('application')"
        ]
        assert not any(
            name.endswith((".db", ".env", ".foamtrame-port", ".dat"))
            for name in package.namelist()
        )


def test_invalid_platform_creates_nothing(tmp_path: Path):
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Unsupported"):
        build_distribution("unsupported", output, root=tmp_path)
    assert not output.exists()


def test_git_failure_does_not_create_a_deliverable(tmp_path: Path):
    output = tmp_path / "output"
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    with pytest.raises(subprocess.CalledProcessError):
        build_distribution(PLATFORMS[0], output, root=tmp_path)
    assert not output.exists()


def test_rebuilding_same_commit_is_reproducible(repository: Path, tmp_path: Path):
    first = build_distribution(PLATFORMS[0], tmp_path / "first", root=repository)
    second = build_distribution(PLATFORMS[0], tmp_path / "second", root=repository)
    assert first.name == second.name
    assert first.read_bytes() == second.read_bytes()
    assert (
        first.with_suffix(".zip.sha256").read_bytes()
        == second.with_suffix(".zip.sha256").read_bytes()
    )


def test_binary_assets_survive_distribution(repository: Path, tmp_path: Path):
    content = bytes(range(256))
    (repository / "static" / "asset.bin").write_bytes(content)
    subprocess.run(["git", "add", "static/asset.bin"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "Binary asset",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    archive = build_distribution(PLATFORMS[1], tmp_path / "output", root=repository)
    with zipfile.ZipFile(archive) as package:
        assert package.read("FOAMTrame/static/asset.bin") == content
