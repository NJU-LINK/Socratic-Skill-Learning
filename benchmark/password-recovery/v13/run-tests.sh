#!/bin/bash
set -e

TEST_DIR="$(dirname "$0")"

if ! command -v pytest &>/dev/null; then
    if command -v uv &>/dev/null; then
        uv pip install pytest -q
    elif python3 -m pip install pytest --break-system-packages -q 2>/dev/null; then
        :
    else
        sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
        sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
        apt-get update -qq && apt-get install -y -qq --no-install-recommends python3-pytest
    fi
fi

exec python3 -m pytest "$TEST_DIR" -v
