#!/bin/bash
set -euo pipefail

install -m 0644 /tmp/task/gen/sample_module.wat /app/sample_module.wat
install -m 0644 /tmp/task/gen/sample_transform.c /app/sample_transform.c
install -m 0644 /tmp/task/gen/sample_contract.json /app/contract.json
wat2wasm /app/sample_module.wat -o /app/module.wasm
gcc -shared -fPIC -O2 /app/sample_transform.c -o /app/libcompute.so
