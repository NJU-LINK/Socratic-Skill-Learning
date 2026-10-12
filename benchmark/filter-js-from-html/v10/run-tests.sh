#!/bin/bash
set -euo pipefail

if command -v uv >/dev/null 2>&1; then
  uv pip install --system pytest selenium beautifulsoup4
else
  python -m pip install pytest selenium beautifulsoup4
fi

pytest -q /tests/test_filter.py
