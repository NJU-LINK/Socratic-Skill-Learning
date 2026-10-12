#!/bin/bash

set -euo pipefail

pip install pytest requests psutil grpcio==1.73.0 grpcio-tools==1.73.0

pytest "$TEST_DIR/test_outputs.py" -rA
