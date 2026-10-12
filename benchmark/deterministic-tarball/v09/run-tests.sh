#!/bin/bash
set -euo pipefail

python3 -m pip show pytest >/dev/null 2>&1 || python3 -m pip install --break-system-packages pytest
python3 -m pytest -q "${TEST_DIR:-$(dirname "$0")/tests}"
