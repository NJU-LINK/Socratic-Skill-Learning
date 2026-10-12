#!/bin/bash
set -euo pipefail

cat > /app/run_pipeline.sh <<'EOF'
#!/bin/bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if ! python3 -c 'import wasmtime' >/dev/null 2>&1; then
  site_dir=/tmp/wasm-pipeline-site
  if [ ! -f "$site_dir/.ready" ]; then
    rm -rf "$site_dir"
    mkdir -p "$site_dir"
    if command -v uv >/dev/null 2>&1; then
      uv pip install --target "$site_dir" wasmtime
    elif python3 -m pip --version >/dev/null 2>&1; then
      python3 -m pip install --target "$site_dir" wasmtime
    else
      echo "either uv or python3 -m pip is required to install wasmtime" >&2
      exit 1
    fi
    touch "$site_dir/.ready"
  fi
  export PYTHONPATH="$site_dir${PYTHONPATH:+:$PYTHONPATH}"
fi

python3 - <<'PY'
from pathlib import Path
import ctypes

import wasmtime


def main() -> None:
    wasm_path = "/app/module.wasm"
    lib_path = "/app/libcompute.so"
    seed_path = "/app/seed.bin"
    output_path = Path("/app/output.txt")

    seed = Path(seed_path).read_bytes()

    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    module = wasmtime.Module.from_file(engine, wasm_path)
    instance = wasmtime.Instance(store, module, [])
    exports = instance.exports(store)

    try:
        memory = exports["memory"]
    except KeyError as exc:
        raise RuntimeError("module does not export memory") from exc

    memory_len = memory.data_len(store)
    if len(seed) > memory_len:
        raise RuntimeError("seed.bin does not fit in wasm memory")

    seed_ptr = memory_len - len(seed)
    memory.write(store, seed, seed_ptr)

    init = exports["init"]
    produce = exports["produce"]

    init(store, seed_ptr)
    data_ptr = int(produce(store))

    if data_ptr < 0 or data_ptr + 16 > memory.data_len(store):
        raise RuntimeError("produce returned an invalid buffer offset")

    data = bytes(memory.read(store, data_ptr, data_ptr + 16))
    if len(data) != 16:
        raise RuntimeError("failed to read the 16-byte result buffer")

    lib = ctypes.CDLL(lib_path)
    lib.transform.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
    lib.transform.restype = ctypes.c_int64

    buf = (ctypes.c_uint8 * 16).from_buffer_copy(data)
    result = int(lib.transform(buf))
    output_path.write_text(f"{result}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
PY
EOF

chmod +x /app/run_pipeline.sh
