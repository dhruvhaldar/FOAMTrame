# Bundled uv runtime

FOAMTrame vendors the official compressed `uv 0.10.12` executables for the two
supported standalone targets:

- Windows x86_64: `uv-x86_64-pc-windows-msvc.zip`
- Linux x86_64 (glibc): `uv-x86_64-unknown-linux-gnu.tar.gz`

The archives and adjacent `.sha256` files are unmodified assets from the
[Astral uv 0.10.12 release](https://github.com/astral-sh/uv/releases/tag/0.10.12).
`uv_bootstrap.py` verifies the pinned checksum before extracting only the `uv`
executable into the ignored `.foamtrame-tools/` directory.

uv is distributed under the included Apache-2.0 and MIT licenses. Update the
version, both archives, both checksum files, licenses, and the constants in
`uv_bootstrap.py` together.
