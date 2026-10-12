#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/solution.sh" ]; then
  SOLUTION_PATH="$(realpath "$SCRIPT_DIR/solution.sh")"
elif [ -f ./solution.sh ]; then
  SOLUTION_PATH="$(realpath ./solution.sh)"
else
  echo "solution.sh not found" >&2
  exit 1
fi

if [ -n "${TEST_DIR:-}" ] && [ -f "$TEST_DIR/test_outputs.py" ]; then
  TEST_PATH="$(realpath "$TEST_DIR/test_outputs.py")"
elif [ -f "$SCRIPT_DIR/tests/test_outputs.py" ]; then
  TEST_PATH="$(realpath "$SCRIPT_DIR/tests/test_outputs.py")"
elif [ -f ./tests/test_outputs.py ]; then
  TEST_PATH="$(realpath ./tests/test_outputs.py)"
else
  echo "tests/test_outputs.py not found" >&2
  exit 1
fi

python3 -m pip install --break-system-packages pytest

bash "$SOLUTION_PATH"

pytest "$TEST_PATH" -rA
