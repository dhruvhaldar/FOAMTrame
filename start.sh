#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="$(bash ./python_bootstrap.sh)"
UV_BIN="$($PYTHON_BIN ./uv_bootstrap.py)"
exec "$UV_BIN" run --quiet --locked --no-dev python ./run.py "$@"
