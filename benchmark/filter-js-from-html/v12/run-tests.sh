#!/bin/bash
set -euo pipefail

SCRIPT_PATH=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$0")
SCRIPT_DIR=$(dirname -- "$SCRIPT_PATH")
PYTHON_BIN=${PYTHON_BIN:-python}

if "$PYTHON_BIN" -c 'import pytest, bs4' >/dev/null 2>&1; then
  :
elif command -v uv >/dev/null 2>&1; then
  uv pip install --system pytest beautifulsoup4
else
  "$PYTHON_BIN" -m pip install pytest beautifulsoup4
fi

cd "$SCRIPT_DIR"
pytest -q tests
