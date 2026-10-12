#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(python3 -c 'import os,sys; print(os.path.dirname(os.path.realpath(sys.argv[1])))' "$0")"
if [[ -n "${TEST_DIR:-}" ]]; then
    TEST_DIR="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$TEST_DIR")"
else
    TEST_DIR="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${SCRIPT_DIR}/tests")"
fi

install_python_tools() {
    if command -v uv >/dev/null 2>&1; then
        uv run --with pytest --with wasmtime pytest "$TEST_DIR" "$@"
        return
    fi

    if ! python3 -m pip --version >/dev/null 2>&1; then
        python3 -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi

    if ! python3 -m pip --version >/dev/null 2>&1; then
        sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
        sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
        apt-get update
        apt-get install -y --no-install-recommends python3-pip
    fi

    python3 -m pip install --quiet --break-system-packages pytest wasmtime
    pytest "$TEST_DIR" "$@"
}

install_python_tools "$@"
