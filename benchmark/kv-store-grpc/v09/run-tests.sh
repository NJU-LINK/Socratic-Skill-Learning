#!/bin/bash
set -euo pipefail

if command -v pip >/dev/null 2>&1; then
    pip install --break-system-packages pytest
else
    uv pip install --system pytest
fi

pytest "$TEST_DIR/test_outputs.py" -rA
