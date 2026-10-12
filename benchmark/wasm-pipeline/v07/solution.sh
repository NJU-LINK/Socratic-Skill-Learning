#!/bin/bash
set -euo pipefail

cat > /app/run_pipeline.sh <<'EOF'
#!/bin/bash
set -euo pipefail

if ! command -v node >/dev/null 2>&1 && ! command -v nodejs >/dev/null 2>&1; then
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    apt-get install -y --no-install-recommends nodejs
    rm -rf /var/lib/apt/lists/*
fi

node_bin="$(command -v node || command -v nodejs)"
payload_path="$(mktemp)"
cleanup() {
    rm -f "$payload_path"
}
trap cleanup EXIT

"$node_bin" - <<'NODE' "$payload_path"
const fs = require('fs');

async function main() {
  const payloadPath = process.argv[2];
  const contract = JSON.parse(fs.readFileSync('/app/contract.json', 'utf8'));
  const wasmBytes = fs.readFileSync('/app/module.wasm');
  const { instance } = await WebAssembly.instantiate(wasmBytes, {});

  const memoryExport = instance.exports[contract.memory_export];
  const functionExport = instance.exports[contract.wasm_function];

  if (!(memoryExport instanceof WebAssembly.Memory)) {
    throw new Error(`Export ${contract.memory_export} is not a WebAssembly.Memory`);
  }
  if (typeof functionExport !== 'function') {
    throw new Error(`Export ${contract.wasm_function} is not callable`);
  }

  const pointer = Number(functionExport());
  if (!Number.isInteger(pointer) || pointer < 0) {
    throw new Error(`Invalid pointer returned from ${contract.wasm_function}: ${pointer}`);
  }

  const memoryView = new Uint8Array(memoryExport.buffer);
  const end = pointer + 16;
  if (end > memoryView.length) {
    throw new Error(`Pointer range ${pointer}-${end} exceeds memory size ${memoryView.length}`);
  }

  fs.writeFileSync(payloadPath, Buffer.from(memoryView.slice(pointer, end)));
}

main().catch((error) => {
  console.error(error.stack || String(error));
  process.exit(1);
});
NODE

python3 - <<'PY' "$payload_path"
import ctypes
import json
import sys
from pathlib import Path


payload = Path(sys.argv[1]).read_bytes()
if len(payload) != 16:
    raise SystemExit(f"expected 16 bytes from wasm memory, got {len(payload)}")

contract = json.loads(Path('/app/contract.json').read_text())
library = ctypes.CDLL('/app/libcompute.so')
symbol = getattr(library, contract['so_symbol'])
symbol.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
symbol.restype = ctypes.c_int64
buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
result = int(symbol(buffer))
Path('/app/output.txt').write_text(f'{result}\n')
PY
EOF

chmod +x /app/run_pipeline.sh
/app/run_pipeline.sh
