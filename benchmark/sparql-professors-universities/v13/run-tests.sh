#!/bin/bash
set -euo pipefail

test_path="${TEST_DIR}"
if [ -d "${TEST_DIR}/tests" ]; then
  test_path="${TEST_DIR}/tests"
fi

python3 -m pytest -q "$test_path"
