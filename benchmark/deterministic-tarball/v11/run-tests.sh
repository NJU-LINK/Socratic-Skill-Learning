#!/bin/bash
set -euo pipefail

python3 -m pip install --quiet --break-system-packages pytest

test_root=${TEST_DIR:-/tests}
if [ -d "$test_root/tests" ]; then
    test_root="$test_root/tests"
fi

pytest -q "$test_root"
