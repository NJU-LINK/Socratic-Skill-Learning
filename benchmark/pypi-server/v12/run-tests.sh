#!/bin/bash

set -euo pipefail

TEST_ROOT="${TEST_DIR:-/app}"
if [ -d "$TEST_ROOT/tests" ]; then
    TEST_PATH="$TEST_ROOT/tests"
else
    TEST_PATH="$TEST_ROOT"
fi

python3 -m pip install --upgrade pytest
python3 -m pytest -q "$TEST_PATH"
