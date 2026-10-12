#!/bin/bash
set -euo pipefail

PYTHON_BIN="$(command -v python3 || command -v python)"

if command -v uv >/dev/null 2>&1; then
  uv pip install --system pytest
else
  "$PYTHON_BIN" -m pip install pytest
fi

"$PYTHON_BIN" -m pytest -q /tests
