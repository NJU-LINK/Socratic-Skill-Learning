#!/bin/bash
set -euo pipefail

if python3 -c 'import pytest' >/dev/null 2>&1; then
  python3 -m pytest /tests "$@"
elif command -v uv >/dev/null 2>&1; then
  uv tool run --from pytest pytest /tests "$@"
else
  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  apt-get update >/dev/null
  apt-get install -y --no-install-recommends python3-pytest >/dev/null
  python3 -m pytest /tests "$@"
fi
