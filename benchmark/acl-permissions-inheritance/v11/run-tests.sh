#!/bin/bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    uv venv /tmp/tb-venv
    . /tmp/tb-venv/bin/activate
    uv pip install pytest
elif python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip install pytest
else
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pytest
fi

pytest -q /tests
