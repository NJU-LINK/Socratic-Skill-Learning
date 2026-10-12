#!/bin/bash
set -euo pipefail

bash /tests/solution.sh

if command -v uv >/dev/null 2>&1; then
  uv pip install --system pytest beautifulsoup4 selenium
else
  python3 -m pip install pytest beautifulsoup4 selenium
fi

python3 -m pytest -q /tests/test_filter.py
