#!/bin/bash
set -e
uv venv .tbench-testing 2>/dev/null || true
source .tbench-testing/bin/activate 2>/dev/null || true
uv pip install pytest==8.4.1 -q 2>/dev/null || true
uv run pytest "$TEST_DIR/test_outputs.py" -rA
