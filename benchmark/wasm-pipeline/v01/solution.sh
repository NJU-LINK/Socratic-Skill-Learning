#!/bin/bash
set -euo pipefail

cat > /app/run_pipeline.sh <<'EOF'
#!/bin/bash
set -euo pipefail

payload_file="$(mktemp)"
trap 'rm -f "$payload_file"' EXIT

node - "$payload_file" <<'NODE'
const fs = require("fs");

(async () => {
  const output = process.argv[2];
  const bytes = fs.readFileSync("/app/module.wasm");
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const { memory, produce, produce_len: produceLen } = instance.exports;
  if (!(memory instanceof WebAssembly.Memory)) throw new Error("missing memory export");
  if (typeof produce !== "function" || typeof produceLen !== "function") {
    throw new Error("missing produce or produce_len export");
  }
  const pointer = Number(produce());
  const length = Number(produceLen());
  if (!Number.isInteger(pointer) || !Number.isInteger(length) || pointer < 0 || length < 0) {
    throw new Error("invalid pointer or length");
  }
  if (pointer + length > memory.buffer.byteLength) throw new Error("buffer is out of bounds");
  fs.writeFileSync(output, Buffer.from(new Uint8Array(memory.buffer, pointer, length)));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
NODE

python3 - "$payload_file" <<'PY'
import ctypes
import sys
from pathlib import Path

payload = Path(sys.argv[1]).read_bytes()
buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
library = ctypes.CDLL("/app/libcompute.so")
library.transform.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
library.transform.restype = ctypes.c_int64
result = int(library.transform(buffer, len(payload)))
Path("/app/output.txt").write_text(f"{result}\n", encoding="utf-8")
PY
EOF

chmod +x /app/run_pipeline.sh
/app/run_pipeline.sh
