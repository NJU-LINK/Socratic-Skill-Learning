#!/bin/bash
set -euo pipefail

PYTHON_BIN="$(command -v python3 || command -v python)"
TEST_DIR="${TEST_DIR:-/tests}"

if command -v uv >/dev/null 2>&1; then
  uv pip install --system pytest==8.4.1
elif "$PYTHON_BIN" -m pip install pytest==8.4.1; then
  :
else
  "$PYTHON_BIN" -m pip install --break-system-packages pytest==8.4.1
fi

"$PYTHON_BIN" -m pytest "$TEST_DIR/test_outputs.py" -rA
