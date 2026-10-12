#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd -P)"

need_apt=0
packages=()

if ! python3 -m pytest --version >/dev/null 2>&1; then
    need_apt=1
    packages+=(python3-pytest)
fi

if ! command -v wat2wasm >/dev/null 2>&1; then
    need_apt=1
    packages+=(wabt)
fi

if [ "$need_apt" -eq 1 ]; then
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    apt-get install -y --no-install-recommends "${packages[@]}"
    rm -rf /var/lib/apt/lists/*
fi

cd "$SCRIPT_DIR"
python3 -m pytest -q tests
