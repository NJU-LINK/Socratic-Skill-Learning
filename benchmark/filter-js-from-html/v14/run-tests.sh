#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEST_DIR=$(realpath "${SCRIPT_DIR%/}/tests")

if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest beautifulsoup4
else
    python -m pip install pytest beautifulsoup4
fi

pytest -q "$TEST_DIR"
