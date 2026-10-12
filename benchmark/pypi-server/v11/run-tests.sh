#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

if command -v uv >/dev/null 2>&1; then
    uv pip install --system pytest
else
    python3 -m pip install pytest
fi

pytest -q tests "$@"
