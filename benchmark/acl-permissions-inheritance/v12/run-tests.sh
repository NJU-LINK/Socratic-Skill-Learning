#!/bin/bash

set -euo pipefail

if command -v pytest >/dev/null 2>&1; then
    :
elif command -v uv >/dev/null 2>&1; then
    uv tool install --with pytest pytest >/tmp/uv-pytest-install.log 2>&1 || cat /tmp/uv-pytest-install.log
    export PATH="$HOME/.local/bin:$PATH"
elif python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip install pytest >/tmp/pip-pytest-install.log 2>&1 || cat /tmp/pip-pytest-install.log
else
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pytest
fi

pytest -q /tests
