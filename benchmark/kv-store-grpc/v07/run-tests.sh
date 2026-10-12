#!/bin/bash

# Install test dependencies
pip install pytest

pytest "$TEST_DIR/test_outputs.py" -rA
