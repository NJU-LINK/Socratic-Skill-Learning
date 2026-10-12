#!/bin/bash

set -e

pip install pytest openpyxl -q

python3 -m pytest /tests/test_outputs.py -rA
