#!/bin/bash
set -euo pipefail

if ! python3 -c "import pytest" >/dev/null 2>&1; then
  python3 -m pip install --quiet --break-system-packages pytest
fi

test_dir="/app/tests"
if [ ! -d "$test_dir" ]; then
  test_dir="$(dirname "$0")/tests"
fi

test_dir="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$test_dir")"

python3 -m pytest -q "$test_dir"
