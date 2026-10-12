#!/bin/bash
set -euo pipefail

if command -v pytest >/dev/null 2>&1; then
  pytest -q "$@" /tests
  exit $?
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --system pytest >/dev/null
else
  python -m pip install pytest >/dev/null
fi

pytest -q "$@" /tests
