#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import importlib.util
import subprocess
import sys

if importlib.util.find_spec("pytest") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pytest"])
PY

python3 -m pytest -q /tests/test_outputs.py
