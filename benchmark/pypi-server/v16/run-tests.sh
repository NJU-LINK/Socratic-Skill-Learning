#!/bin/bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
VENV_DIR="$SCRIPT_DIR/.test-venv"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --quiet pytest
cd "$SCRIPT_DIR"
"$VENV_DIR/bin/python" -m pytest -q tests
