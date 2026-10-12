#!/bin/bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest
else
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pytest
fi

python3 -m pytest -q /tests
