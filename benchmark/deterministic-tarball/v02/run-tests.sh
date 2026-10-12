#!/bin/bash
set -euo pipefail

python3 -m pip install --quiet --break-system-packages pytest
pytest -q /tests/test_outputs.py
