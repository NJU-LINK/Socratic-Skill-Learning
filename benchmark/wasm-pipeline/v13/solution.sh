#!/bin/bash
set -euo pipefail

app_root="${APP_ROOT:-/app}"

mkdir -p "$app_root"

cat > "$app_root/run_pipeline.sh" <<'EOF'
#!/bin/bash
set -euo pipefail

app_root="${APP_ROOT:-/app}"
tmp_json="$(mktemp)"
cleanup() {
  rm -f "$tmp_json"
}
trap cleanup EXIT

node - "$app_root/module.wasm" "$tmp_json" <<'NODE'
const fs = require('fs');

async function main() {
  const [wasmPath, jsonPath] = process.argv.slice(2);
  const wasmBytes = fs.readFileSync(wasmPath);
  const { instance } = await WebAssembly.instantiate(wasmBytes, {});
  const exports = instance.exports;

  if (typeof exports.seed_state === 'function') {
    exports.seed_state();
  }

  if (typeof exports.produce !== 'function') {
    throw new Error('module does not export produce()');
  }
  if (!(exports.memory instanceof WebAssembly.Memory)) {
    throw new Error('module does not export linear memory as memory');
  }

  const ptr = Number(exports.produce());
  if (!Number.isInteger(ptr) || ptr < 0) {
    throw new Error(`invalid produce() pointer: ${ptr}`);
  }

  const view = new Uint8Array(exports.memory.buffer, ptr, 16);
  fs.writeFileSync(jsonPath, JSON.stringify(Array.from(view)));
}

main().catch((err) => {
  console.error(err instanceof Error ? err.stack : String(err));
  process.exit(1);
});
NODE

python3 - "$app_root/libcompute.so" "$tmp_json" "$app_root/output.txt" <<'PY'
import ctypes
import json
import sys

lib_path, data_path, out_path = sys.argv[1:4]

with open(data_path, 'r', encoding='utf-8') as fh:
    values = json.load(fh)

buf = (ctypes.c_uint8 * len(values))(*values)
lib = ctypes.CDLL(lib_path)
lib.transform.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
lib.transform.restype = ctypes.c_int64
result = int(lib.transform(buf))

with open(out_path, 'w', encoding='utf-8') as fh:
    fh.write(str(result))
PY
EOF

chmod +x "$app_root/run_pipeline.sh"
