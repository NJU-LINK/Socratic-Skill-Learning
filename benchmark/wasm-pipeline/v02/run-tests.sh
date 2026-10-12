#!/bin/bash
set -euo pipefail

VENV_DIR="/tmp/wasm-pipeline-tests-venv"

if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV_DIR"
    uv pip install --python "$VENV_DIR/bin/python" pytest
    PYTHON_BIN="$VENV_DIR/bin/python"
elif python3 -m ensurepip --help >/dev/null 2>&1; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m ensurepip --upgrade
    "$VENV_DIR/bin/python" -m pip install pytest
    PYTHON_BIN="$VENV_DIR/bin/python"
elif python3 -m pip --version >/dev/null 2>&1; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install pytest
    PYTHON_BIN="$VENV_DIR/bin/python"
else
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    apt-get install -y python3-pytest
    PYTHON_BIN="python3"
fi

SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$(dirname "${BASH_SOURCE[0]}")")"
cd "$SCRIPT_DIR"
if [ -d tests ]; then
    "$PYTHON_BIN" -m pytest -q tests
else
    "$PYTHON_BIN" -m pytest -q .
fi
