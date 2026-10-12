#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v uv >/dev/null 2>&1; then
  uv run --with pytest pytest -q tests
else
  PYTHON_BIN="$(command -v python3 || command -v python)"
  "$PYTHON_BIN" -m pip install --quiet pytest
  "$PYTHON_BIN" -m pytest -q tests
fi
