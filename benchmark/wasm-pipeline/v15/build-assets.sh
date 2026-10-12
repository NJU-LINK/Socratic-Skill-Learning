#!/bin/bash
set -euo pipefail

install -m 0644 /tmp/task/gen/sample_module.wat /app/sample_module.wat
install -m 0644 /tmp/task/gen/sample_transform.c /app/sample_transform.c
install -m 0644 /tmp/task/gen/sample_seed.txt /app/sample_seed.txt
install -m 0644 /tmp/task/gen/seed.bin /app/seed.bin
wat2wasm /app/sample_module.wat -o /app/module.wasm
gcc -shared -fPIC -O2 /app/sample_transform.c -o /app/libcompute.so
