#!/bin/bash
set -euo pipefail

TEST_VENV="/tmp/vectorops-test-venv"

rm -rf "$TEST_VENV"
python3 -m venv "$TEST_VENV"
"$TEST_VENV/bin/python" -m pip install --upgrade pip
"$TEST_VENV/bin/python" -m pip install pytest

TEST_DIR="/tests"
if [[ ! -d "$TEST_DIR" ]]; then
    TEST_DIR="$(dirname "$0")/tests"
fi

"$TEST_VENV/bin/python" -m pytest -q "$TEST_DIR"
