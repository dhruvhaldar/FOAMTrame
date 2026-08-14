from __future__ import annotations

import hashlib
import os
import platform
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
UV_VERSION = "0.10.12"
VENDOR_ROOT = PROJECT_ROOT / "vendor" / "uv" / UV_VERSION
INSTALL_ROOT = PROJECT_ROOT / ".foamtrame-tools" / "uv" / UV_VERSION


@dataclass(frozen=True)
class UvBundle:
    archive: str
    sha256: str
    member: str
    executable: str


UV_BUNDLES = {
    ("Windows", "x86_64"): UvBundle(
        archive="uv-x86_64-pc-windows-msvc.zip",
        sha256="4c1d55501869b3330d4aabf45ad6024ce2367e0f3af83344395702d272c22e88",
        member="uv.exe",
        executable="uv.exe",
    ),
    ("Linux", "x86_64"): UvBundle(
        archive="uv-x86_64-unknown-linux-gnu.tar.gz",
        sha256="ec72570c9d1f33021aa80b176d7baba390de2cfeb1abcbefca346d563bf17484",
        member="uv-x86_64-unknown-linux-gnu/uv",
        executable="uv",
    ),
}


def normalized_machine(machine: str | None = None) -> str:
    value = (machine or platform.machine()).strip().lower()
    if value in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    return value


def bundled_uv_path(
    *, system: str | None = None, machine: str | None = None
) -> tuple[Path, UvBundle]:
    platform_key = (system or platform.system(), normalized_machine(machine))
    bundle = UV_BUNDLES.get(platform_key)
    if bundle is None:
        raise RuntimeError(
            "No bundled uv binary is available for "
            f"{platform_key[0]} {platform_key[1]}. Install uv on PATH or use a "
            "supported Windows/Linux x86_64 computer."
        )
    return INSTALL_ROOT / bundle.executable, bundle


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_executable(archive: Path, bundle: UvBundle) -> bytes:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as package:
            return package.read(bundle.member)

    with tarfile.open(archive, mode="r:gz") as package:
        member = package.getmember(bundle.member)
        if not member.isfile():
            raise RuntimeError(f"Bundled uv member is not a file: {bundle.member}")
        stream = package.extractfile(member)
        if stream is None:
            raise RuntimeError(f"Could not read bundled uv member: {bundle.member}")
        return stream.read()


def install_bundled_uv(
    *, system: str | None = None, machine: str | None = None
) -> Path:
    selected_system = system or platform.system()
    executable, bundle = bundled_uv_path(system=system, machine=machine)
    if executable.is_file():
        return executable

    archive = VENDOR_ROOT / bundle.archive
    if not archive.is_file():
        raise RuntimeError(
            f"Bundled uv archive is missing: {archive}. Restore the vendor/uv "
            "directory or install uv on PATH."
        )
    actual_hash = sha256_file(archive)
    if actual_hash != bundle.sha256:
        raise RuntimeError(
            f"Bundled uv archive failed SHA-256 verification: {archive.name}"
        )

    executable.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=executable.parent,
            prefix=f".{executable.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(_archive_executable(archive, bundle))
        if selected_system != "Windows":
            temporary.chmod(0o755)
        os.replace(temporary, executable)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return executable


def resolve_uv() -> Path:
    system_uv = shutil.which("uv")
    if system_uv:
        return Path(system_uv)
    return install_bundled_uv()


if __name__ == "__main__":
    try:
        print(resolve_uv())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
