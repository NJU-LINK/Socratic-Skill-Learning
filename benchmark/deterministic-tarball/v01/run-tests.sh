#!/bin/bash
set -euo pipefail

test_root="${TEST_DIR:-$(dirname "$0")}"
pytest_target="$test_root"

if [ -d "$test_root/tests" ]; then
    pytest_target="$test_root/tests"
fi

if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest
    python3 -m pytest -q "$pytest_target"
else
    python3 -m pip install --break-system-packages pytest
    python3 -m pytest -q "$pytest_target"
fi
