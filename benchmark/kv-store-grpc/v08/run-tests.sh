#!/bin/bash
set -e

pip install pytest requests psutil

pytest "$TEST_DIR/test_outputs.py" -rA
