#!/bin/bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$script_dir"

if command -v uv >/dev/null 2>&1; then
    uv run --with pytest --with beautifulsoup4 pytest -q tests
else
    python -m pip install --break-system-packages pytest beautifulsoup4
    pytest -q tests
fi
