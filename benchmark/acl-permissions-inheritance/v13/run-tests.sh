#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
cd "$SCRIPT_DIR"

if command -v uv >/dev/null 2>&1; then
  uv run --with pytest pytest tests -q
elif command -v pytest >/dev/null 2>&1; then
  pytest tests -q
else
  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3-pytest
  python3 -m pytest tests -q
fi
