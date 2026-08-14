from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import pytest

import uv_bootstrap


def test_resolve_uv_prefers_an_existing_system_install(monkeypatch):
    monkeypatch.setattr(uv_bootstrap.shutil, "which", lambda _command: "/tools/uv")
    monkeypatch.setattr(
        uv_bootstrap,
        "install_bundled_uv",
        lambda: (_ for _ in ()).throw(AssertionError("bundle should not be extracted")),
    )

    assert uv_bootstrap.resolve_uv() == Path("/tools/uv")


def test_missing_system_uv_is_verified_and_extracted_locally(monkeypatch, tmp_path):
    archive_name = "uv-test.zip"
    archive = tmp_path / "vendor" / archive_name
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("uv.exe", b"test uv executable")

    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    bundle = uv_bootstrap.UvBundle(
        archive=archive_name,
        sha256=checksum,
        member="uv.exe",
        executable="uv.exe",
    )
    monkeypatch.setattr(uv_bootstrap, "VENDOR_ROOT", archive.parent)
    monkeypatch.setattr(uv_bootstrap, "INSTALL_ROOT", tmp_path / "tools")
    monkeypatch.setattr(uv_bootstrap, "UV_BUNDLES", {("Windows", "x86_64"): bundle})

    executable = uv_bootstrap.install_bundled_uv(system="Windows", machine="AMD64")

    assert executable == tmp_path / "tools" / "uv.exe"
    assert executable.read_bytes() == b"test uv executable"


def test_tampered_bundled_uv_is_rejected(monkeypatch, tmp_path):
    archive = tmp_path / "uv-test.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("uv.exe", b"tampered")

    bundle = uv_bootstrap.UvBundle(
        archive=archive.name,
        sha256="0" * 64,
        member="uv.exe",
        executable="uv.exe",
    )
    monkeypatch.setattr(uv_bootstrap, "VENDOR_ROOT", tmp_path)
    monkeypatch.setattr(uv_bootstrap, "INSTALL_ROOT", tmp_path / "tools")
    monkeypatch.setattr(uv_bootstrap, "UV_BUNDLES", {("Windows", "x86_64"): bundle})

    with pytest.raises(RuntimeError, match="failed SHA-256 verification"):
        uv_bootstrap.install_bundled_uv(system="Windows", machine="x86_64")


def test_unsupported_platform_requires_a_system_uv():
    with pytest.raises(RuntimeError, match="No bundled uv binary is available"):
        uv_bootstrap.bundled_uv_path(system="Linux", machine="aarch64")


@pytest.mark.parametrize("platform_key,bundle", uv_bootstrap.UV_BUNDLES.items())
def test_vendored_uv_archives_match_pinned_checksums(platform_key, bundle):
    del platform_key
    archive = uv_bootstrap.VENDOR_ROOT / bundle.archive
    official_checksum = archive.with_name(f"{archive.name}.sha256")
    assert archive.is_file()
    assert official_checksum.read_text(encoding="utf-8").split()[0] == bundle.sha256
    assert uv_bootstrap.sha256_file(archive) == bundle.sha256
