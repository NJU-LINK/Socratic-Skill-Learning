#!/bin/bash
set -e

uv venv .tbench-testing 2>/dev/null || true
. .tbench-testing/bin/activate 2>/dev/null || true
uv pip install pytest 2>/dev/null || true

uv run pytest "$TEST_DIR/test_outputs.py" -v --tb=long
