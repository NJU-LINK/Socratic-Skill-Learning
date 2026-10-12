#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
VENV_DIR="$SCRIPT_DIR/.venv"

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
else
    PYTHON=python
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV_DIR/bin/python" pytest beautifulsoup4
else
    "$VENV_DIR/bin/python" -m pip install pytest beautifulsoup4
fi

cd "$SCRIPT_DIR"
"$VENV_DIR/bin/python" -m pytest -q tests
