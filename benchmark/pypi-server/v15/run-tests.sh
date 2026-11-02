#!/bin/bash
set -euo pipefail

cd /app

TEST_VENV="/tmp/vectorops-test-venv"
python3 -m venv "$TEST_VENV"
"$TEST_VENV/bin/python" -m pip install --quiet pytest
"$TEST_VENV/bin/pytest" -q "$TEST_DIR/test_outputs.py"
