#!/bin/bash
set -e

uv venv /tmp/.tbench-testing 2>/dev/null || true
. /tmp/.tbench-testing/bin/activate 2>/dev/null || true
uv pip install pytest 2>/dev/null || python3 -m pip install --user --break-system-packages pytest 2>/dev/null || true

cd /tests
exec python3 -m pytest -v --tb=short 2>&1
