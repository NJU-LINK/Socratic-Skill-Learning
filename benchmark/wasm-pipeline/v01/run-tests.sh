#!/bin/bash
set -euo pipefail

TEST_ROOT="${TEST_DIR:-$(dirname "$0")/tests}"

if ! python3 -m pytest --version >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
        uv tool run --with pytest pytest --version >/dev/null
        exec uv tool run --with pytest pytest -q "" ""
    fi
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
    apt-get update
    apt-get install -y python3-pytest
fi

pytest -q "$TEST_ROOT" "$@"
