#!/bin/bash
set -euo pipefail

python3 -m pytest "$TEST_DIR" -rA
