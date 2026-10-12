#!/bin/bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest
elif command -v pip3 >/dev/null 2>&1; then
    pip3 install --break-system-packages pytest
else
    python3 -m ensurepip --upgrade
    python3 -m pip install --break-system-packages pytest
fi

pytest -q /tests
