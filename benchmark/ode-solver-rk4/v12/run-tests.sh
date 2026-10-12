#!/usr/bin/env bash
set -euo pipefail

python -m pytest "$TEST_DIR" -rA
