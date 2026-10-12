#!/bin/bash
set -euo pipefail

if ! command -v pytest >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
        uv pip install --system pytest
    else
        sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
        sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pytest
    fi
fi

pytest -q /tests
