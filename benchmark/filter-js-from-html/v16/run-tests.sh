#!/bin/bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest
else
    python3 -m pip install pytest
fi

pytest -q /tests/test_filter.py
