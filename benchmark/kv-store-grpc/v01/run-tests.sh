#!/bin/bash

set -euo pipefail

python3 -m pip install --break-system-packages pytest requests psutil

pytest "$TEST_DIR/test_outputs.py" -rA
