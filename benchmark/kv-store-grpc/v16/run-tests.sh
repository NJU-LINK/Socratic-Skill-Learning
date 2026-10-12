#!/bin/bash
set -euo pipefail

python -m pip install pytest requests psutil

pytest "$TEST_DIR/test_outputs.py" -rA
