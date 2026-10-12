#!/usr/bin/env bash
set -euo pipefail

exec python3 -m pytest "${TEST_DIR:-/tests}" -rA
