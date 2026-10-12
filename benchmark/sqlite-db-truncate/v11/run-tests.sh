#!/bin/bash

if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

python3 $TEST_DIR/test_runner.py $TEST_DIR/test_outputs.py
