#!/bin/bash
set -euo pipefail
cd /app
cp /tests/test_outputs.py /app/test_outputs.py
exec python3 -m pytest -q /app/test_outputs.py
