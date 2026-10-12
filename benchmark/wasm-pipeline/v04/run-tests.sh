#!/bin/bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    uv pip install --system --break-system-packages pytest
else
    python3 -m pip install --break-system-packages pytest
fi

python3 -m pytest -q /tests/test_outputs.py
