#!/bin/bash
set -euo pipefail

if ! python3 -c 'import pytest' 2>/dev/null; then
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
    apt-get update && apt-get install -y python3-pytest && rm -rf /var/lib/apt/lists/*
fi

TEST_DIR="${TEST_DIR:-/app/output/tests}"
if [ ! -d "$TEST_DIR" ]; then
    TEST_DIR="$(dirname "$0")/tests"
fi

python3 -m pytest "$TEST_DIR" -v
