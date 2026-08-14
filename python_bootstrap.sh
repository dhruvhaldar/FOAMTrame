#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_VERSION="3.12.13"
ARCHIVE_NAME="cpython-3.12.13+20260807-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
EXPECTED_HASH="506191be3ee7bd190a8834dcdc1b3bc70aab50608deccc711935aa007239cabd"
VENDOR_ARCHIVE="$SCRIPT_DIR/vendor/python/$PYTHON_VERSION/$ARCHIVE_NAME"
TOOLS_ROOT="${FOAMTRAME_TOOLS_DIR:-$SCRIPT_DIR/.foamtrame-tools}"
INSTALL_DIR="$TOOLS_ROOT/python/$PYTHON_VERSION"
BUNDLED_PYTHON="$INSTALL_DIR/bin/python3.12"
PROBE="import platform, sys; ok = platform.python_implementation() == 'CPython' and sys.version_info[:2] == (3, 12); print(sys.executable if ok else ''); raise SystemExit(0 if ok else 1)"

compatible_python() {
  local candidate="$1"
  if ! command -v "$candidate" >/dev/null 2>&1; then
    return 1
  fi
  "$candidate" -c "$PROBE" 2>/dev/null
}

if [[ "${FOAMTRAME_FORCE_BUNDLED_PYTHON:-0}" != "1" ]]; then
  for candidate in python3.12 python3 python; do
    if resolved="$(compatible_python "$candidate")"; then
      printf '%s\n' "$resolved"
      exit 0
    fi
  done
fi

if [[ -x "$BUNDLED_PYTHON" ]]; then
  if resolved="$(compatible_python "$BUNDLED_PYTHON")"; then
    printf '%s\n' "$resolved"
    exit 0
  fi
  printf 'The locally bundled Python installation is invalid: %s\n' "$BUNDLED_PYTHON" >&2
  exit 1
fi

architecture="$(uname -m)"
if [[ "$architecture" != "x86_64" && "$architecture" != "amd64" ]]; then
  printf 'No bundled Python is available for Linux %s. Install CPython 3.12 on PATH.\n' "$architecture" >&2
  exit 1
fi
if [[ ! -f "$VENDOR_ARCHIVE" ]]; then
  printf 'Bundled Python archive is missing: %s\n' "$VENDOR_ARCHIVE" >&2
  exit 1
fi
if command -v sha256sum >/dev/null 2>&1; then
  actual_hash="$(sha256sum "$VENDOR_ARCHIVE" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  actual_hash="$(shasum -a 256 "$VENDOR_ARCHIVE" | awk '{print $1}')"
else
  printf 'sha256sum or shasum is required to verify bundled Python.\n' >&2
  exit 1
fi
if [[ "$actual_hash" != "$EXPECTED_HASH" ]]; then
  printf 'Bundled Python archive failed SHA-256 verification: %s\n' "$ARCHIVE_NAME" >&2
  exit 1
fi
if ! command -v tar >/dev/null 2>&1; then
  printf 'tar is required to extract bundled Python.\n' >&2
  exit 1
fi

install_parent="$(dirname "$INSTALL_DIR")"
temporary_dir="$install_parent/.$PYTHON_VERSION.tmp-$$"
mkdir -p "$temporary_dir"
cleanup() {
  rm -rf -- "$temporary_dir"
}
trap cleanup EXIT
tar -xzf "$VENDOR_ARCHIVE" -C "$temporary_dir" --strip-components=1
if ! compatible_python "$temporary_dir/bin/python3.12" >/dev/null; then
  printf 'The extracted bundled Python executable failed validation.\n' >&2
  exit 1
fi
mv -- "$temporary_dir" "$INSTALL_DIR"
trap - EXIT
printf '%s\n' "$BUNDLED_PYTHON"
