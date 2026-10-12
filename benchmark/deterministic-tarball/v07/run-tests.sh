#!/bin/bash
set -euo pipefail

script_dir=$(dirname -- "$0")

python3 -m pip install --break-system-packages pytest
cd -- "$script_dir"
pytest -q tests
