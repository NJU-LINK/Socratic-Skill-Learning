#!/bin/bash

set -euo pipefail

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

if command -v uv >/dev/null 2>&1; then
    uv venv .tbench-testing
    source .tbench-testing/bin/activate
    uv pip install pytest==8.4.1
else
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
    python3 -m venv .tbench-testing
    source .tbench-testing/bin/activate
    python -m pip install pytest==8.4.1
fi

python -m pytest "$TEST_DIR" -rA
