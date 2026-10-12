#!/bin/bash
set -euo pipefail

cat <<'EOF' >/app/run_pipeline.sh
#!/bin/bash
set -euo pipefail

ensure_python_package() {
    local module_name="$1"
    local package_name="$2"

    if python3 -c "import ${module_name}" >/dev/null 2>&1; then
        return
    fi

    if ! python3 -m pip --version >/dev/null 2>&1; then
        python3 -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi

    if ! python3 -m pip --version >/dev/null 2>&1; then
        sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
        sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources || true
        apt-get update
        apt-get install -y --no-install-recommends python3-pip
    fi

    python3 -m pip install --quiet --break-system-packages "${package_name}"
}

ensure_python_package wasmtime wasmtime

python3 - <<'PY'
import ctypes
import struct
from pathlib import Path

import wasmtime

MODULE_PATH = Path("/app/module.wasm")
LIB_PATH = Path("/app/libcompute.so")
OUTPUT_PATH = Path("/app/output.txt")


def load_payload() -> bytes:
    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    module = wasmtime.Module(engine, MODULE_PATH.read_bytes())
    instance = wasmtime.Instance(store, module, [])
    exports = instance.exports(store)

    produce = exports["produce"]
    memory = exports["memory"]

    header_offset = int(produce(store))
    header = bytes(memory.read(store, header_offset, header_offset + 8))
    if len(header) != 8:
        raise RuntimeError("produce() returned a header outside linear memory")

    payload_offset, payload_length = struct.unpack("<II", header)
    payload = bytes(memory.read(store, payload_offset, payload_offset + payload_length))
    if len(payload) != payload_length:
        raise RuntimeError("payload extends beyond linear memory")

    return payload


def main() -> None:
    payload = load_payload()

    library = ctypes.CDLL(str(LIB_PATH))
    library.transform.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
    library.transform.restype = ctypes.c_uint64

    buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
    result = library.transform(buffer, len(payload))
    OUTPUT_PATH.write_text(f"{int(result)}\n")


if __name__ == "__main__":
    main()
PY
EOF

chmod +x /app/run_pipeline.sh
