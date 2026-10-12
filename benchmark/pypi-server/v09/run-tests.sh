#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$(dirname "$0")")
VENV_DIR=${VENV_DIR:-/tmp/family-pypi-server-tests-venv}

if command -v uv >/dev/null 2>&1; then
  uv venv "$VENV_DIR" >/dev/null
  uv pip install --python "$VENV_DIR/bin/python" pytest twine >/dev/null
else
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install pytest twine >/dev/null
fi

TEST_DIR=$(realpath "$SCRIPT_DIR/tests")
cd /tmp
"$VENV_DIR/bin/python" -m pytest "$TEST_DIR" "$@"
