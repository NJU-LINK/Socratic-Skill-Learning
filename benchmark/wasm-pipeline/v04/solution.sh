#!/bin/bash
set -euo pipefail

sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true

apt-get update
apt-get install -y --no-install-recommends python3 python3-pip ca-certificates

python3 -m pip install --break-system-packages --no-cache-dir wasmtime==35.0.0

cat > /app/run_pipeline.py <<'PY'
#!/usr/bin/env python3
import ctypes as C
import os
from pathlib import Path

from wasmtime import Engine, Instance, Module, Store


WASM_PATH = os.environ.get("WASM_PATH", "/app/module.wasm")
SO_PATH = os.environ.get("SO_PATH", "/app/libcompute.so")
OUT_PATH = Path("/app/output.txt")


def read_region() -> bytes:
    engine = Engine()
    store = Store(engine)
    module = Module.from_file(engine, WASM_PATH)
    instance = Instance(store, module, [])

    exports = instance.exports(store)
    packed = int(exports["produce_region"](store)) & ((1 << 64) - 1)
    length = (packed >> 32) & 0xFFFFFFFF
    offset = packed & 0xFFFFFFFF
    memory = exports["memory"]

    data = memory.read(store, offset, offset + length)
    if len(data) != length:
        raise RuntimeError(
            f"expected {length} bytes from memory at offset {offset}, got {len(data)}"
        )
    return bytes(data)


def transform_region(data: bytes) -> int:
    lib = C.CDLL(SO_PATH)
    lib.transform_region.argtypes = [C.POINTER(C.c_uint8), C.c_uint32]
    lib.transform_region.restype = C.c_int64

    buf = (C.c_uint8 * len(data)).from_buffer_copy(data)
    return int(lib.transform_region(buf, len(data)))


def main() -> None:
    data = read_region()
    result = transform_region(data)
    OUT_PATH.write_text(f"{result}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
PY

cat > /app/run_pipeline.sh <<'SH'
#!/bin/bash
set -euo pipefail
exec python3 /app/run_pipeline.py
SH

chmod +x /app/run_pipeline.py /app/run_pipeline.sh
/app/run_pipeline.sh
