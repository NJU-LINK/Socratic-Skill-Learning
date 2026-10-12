#!/bin/bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    uv venv /tmp/tb-venv
    . /tmp/tb-venv/bin/activate
    uv pip install pytest
elif command -v pip3 >/dev/null 2>&1; then
    pip3 install --break-system-packages pytest
elif command -v apt-get >/dev/null 2>&1; then
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pytest
else
    echo "Unable to install pytest" >&2
    exit 1
fi

pytest -q /tests/test_outputs.py
