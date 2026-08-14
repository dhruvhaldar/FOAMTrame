# Bundled Python runtime

FOAMTrame vendors the official stripped, install-only CPython 3.12.13 archives
from the [Astral python-build-standalone 2026-08-07 release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260807):

- Windows x86_64 MSVC
- Linux x86_64 GNU libc

The adjacent `.sha256` files record the SHA-256 digests published in the GitHub
release metadata. The platform bootstrap script checks for an existing CPython
3.12 interpreter first. When none is available, it verifies and extracts the
matching archive beneath the ignored `.foamtrame-tools/` directory. It does not
modify PATH, the Windows registry, or a system Python installation.

The archives are unmodified upstream assets and contain CPython's `LICENSE.txt`
plus the licenses for bundled components. Update the version, release date,
archives, digests, bootstrap scripts, CI version, and README together.
