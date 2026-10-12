#!/bin/bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
  uv pip install --system --quiet pytest
else
  python3 -m pip install --quiet pytest
fi

pytest -q /tests
