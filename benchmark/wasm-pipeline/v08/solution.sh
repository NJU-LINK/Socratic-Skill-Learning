#!/bin/bash
set -euo pipefail

cat > /app/run_pipeline.sh <<'EOF'
#!/bin/bash
set -euo pipefail

payload_file="$(mktemp)"
trap 'rm -f "$payload_file"' EXIT

node - "$payload_file" <<'NODE'
const fs = require("fs");

function checkedRange(offset, length, total) {
  if (!Number.isInteger(offset) || !Number.isInteger(length) || offset < 0 || length < 0) {
    throw new Error("invalid descriptor range");
  }
  if (offset + length > total) throw new Error("descriptor range is out of bounds");
}

(async () => {
  const output = process.argv[2];
  const bytes = fs.readFileSync("/app/module.wasm");
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const { memory, descriptor } = instance.exports;
  if (!(memory instanceof WebAssembly.Memory)) throw new Error("missing memory export");
  if (typeof descriptor !== "function") throw new Error("missing descriptor export");

  const descriptorOffset = Number(descriptor());
  checkedRange(descriptorOffset, 16, memory.buffer.byteLength);
  const view = new DataView(memory.buffer, descriptorOffset, 16);
  const firstOffset = view.getUint32(0, true);
  const firstLength = view.getUint32(4, true);
  const secondOffset = view.getUint32(8, true);
  const secondLength = view.getUint32(12, true);
  checkedRange(firstOffset, firstLength, memory.buffer.byteLength);
  checkedRange(secondOffset, secondLength, memory.buffer.byteLength);

  const first = Buffer.from(new Uint8Array(memory.buffer, firstOffset, firstLength));
  const second = Buffer.from(new Uint8Array(memory.buffer, secondOffset, secondLength));
  fs.writeFileSync(output, Buffer.concat([first, second]));
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
library.transform.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
library.transform.restype = ctypes.c_int64
result = int(library.transform(buffer, len(payload)))
Path("/app/output.txt").write_text(f"{result}\n", encoding="utf-8")
PY
EOF

chmod +x /app/run_pipeline.sh
/app/run_pipeline.sh
