#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_ROOT="${TEST_DIR:-$SCRIPT_DIR/tests}"
TEST_ROOT="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$TEST_ROOT")"

if ! python3 -m pytest --version >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest
  else
    python3 -m pip install pytest
  fi
fi

python3 -m pytest -q "$TEST_ROOT"
