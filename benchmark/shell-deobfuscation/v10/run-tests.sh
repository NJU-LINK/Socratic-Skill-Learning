#!/bin/bash
set -e

# Install pytest in a uv-managed venv
uv venv /tmp/venv --python 3.12 --quiet
uv pip install --python /tmp/venv/bin/python pytest --quiet

# Run the tests
cd /tests
/tmp/venv/bin/python -m pytest -v --tb=short 2>&1
exit $?
