#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="$(bash ./python_bootstrap.sh)"
exec "$PYTHON_BIN" ./install.py "$@"
