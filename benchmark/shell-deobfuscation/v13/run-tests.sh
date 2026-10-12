#!/bin/bash
set -e

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

python3 -m unittest discover -v -s "$TEST_DIR" -p "test_*.py"
