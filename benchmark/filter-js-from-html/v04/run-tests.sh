#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(dirname -- "$0")

if ! python3 -c "import pytest" >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest >/dev/null
  else
    python3 -m pip install pytest >/dev/null
  fi
fi

cd -- "$SCRIPT_DIR"
pytest -q tests
