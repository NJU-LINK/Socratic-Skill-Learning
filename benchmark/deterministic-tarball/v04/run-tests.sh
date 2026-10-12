#!/bin/bash
set -euo pipefail

if command -v pytest >/dev/null 2>&1; then
    pytest -q /tests
    exit $?
fi

if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest
else
    python3 -m pip install --break-system-packages pytest
fi

pytest -q /tests
