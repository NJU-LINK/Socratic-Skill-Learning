#!/bin/bash
set -euo pipefail

cd /app

python3 -m venv /tmp/Task Author-test-venv
/tmp/Task Author-test-venv/bin/python -m pip install --quiet pytest
/tmp/Task Author-test-venv/bin/pytest -q "$TEST_DIR/test_outputs.py"
