#!/bin/bash
set -e
pip install --quiet pytest 2>/dev/null
cp /tests/test_outputs.py /app/
cd /app
exec python3 -m pytest test_outputs.py -v
