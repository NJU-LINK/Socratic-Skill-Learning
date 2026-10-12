#!/bin/bash
set -euo pipefail

python3 -m pytest -q /tests -rA
