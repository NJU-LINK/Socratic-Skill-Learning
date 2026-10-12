#!/usr/bin/env bash
set -euo pipefail

cd /app
exec python3 -m pytest "${TEST_DIR:-/tests}" -rA
