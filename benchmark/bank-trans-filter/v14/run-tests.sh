#!/bin/bash
set -euo pipefail
exec python3 -m pytest -q /tests/test_outputs.py
