"""Build an installable source archive from committed files, excluding local state."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ("linux-x86_64", "windows-x86_64")


def build_distribution(
    platform: str, output: Path, *, root: Path = PROJECT_ROOT
) -> Path:
    """Archive HEAD rather than the working tree so cases and secrets stay local."""
    if platform not in PLATFORMS:
        raise ValueError(f"Unsupported distribution platform: {platform}")
    revision = subprocess.check_output(  # nosec: fixed Git arguments, no shell execution.
        ["git", "rev-parse", "--short=12", "HEAD"], cwd=root, text=True
    ).strip()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"FOAMTrame-{revision}-{platform}.zip"
    subprocess.run(  # nosec: fixed archive action; output is a single argument, no shell.
        [
            "git",
            "archive",
            "--format=zip",
            "--prefix=FOAMTrame/",
            f"--output={archive}",
            "HEAD",
        ],
        cwd=root,
        check=True,
    )
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    archive.with_suffix(".zip.sha256").write_text(
        f"{digest.hexdigest()}  {archive.name}\n", encoding="utf-8"
    )
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=PLATFORMS, required=True)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    build_distribution(args.platform, args.output)


if __name__ == "__main__":
    main()
