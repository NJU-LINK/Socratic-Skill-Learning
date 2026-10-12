#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest >/tmp/pytest-install.log 2>&1 || python3 -m pip install --break-system-packages pytest >/tmp/pytest-install.log 2>&1
else
    python3 -m pip install --break-system-packages pytest >/tmp/pytest-install.log 2>&1
fi

cd "$SCRIPT_DIR"
pytest -q tests
