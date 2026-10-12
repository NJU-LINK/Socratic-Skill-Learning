#!/usr/bin/env bash
set -euo pipefail

python3 -m pytest "$TEST_DIR/test_outputs.py" -rA
