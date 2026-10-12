#!/bin/bash
set -euo pipefail

python -m pip install pytest

pytest "$TEST_DIR/test_outputs.py" -rA
