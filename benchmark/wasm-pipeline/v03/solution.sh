#!/bin/bash
set -euo pipefail

cat <<'PY' >/app/run_pipeline.py
#!/usr/bin/env python3
import ctypes
import subprocess
import tempfile
from pathlib import Path


RUNNER_C = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "module.h"
#include "wasm-rt.h"

int main(int argc, char** argv) {
  if (argc != 2) {
    fprintf(stderr, "usage: %s <payload-out>\n", argv[0]);
    return 2;
  }

  FILE* out = fopen(argv[1], "wb");
  if (out == NULL) {
    perror("fopen");
    return 1;
  }

  wasm_rt_init();

  w2c_module instance;
  wasm2c_module_instantiate(&instance);

  wasm_rt_memory_t* memory = w2c_module_mem(&instance);
  uint32_t ptr = w2c_module_emit_ptr(&instance);
  uint32_t len = w2c_module_emit_len(&instance);

  if ((uint64_t)ptr + (uint64_t)len > memory->size) {
    fprintf(stderr, "buffer range is outside linear memory\n");
    wasm2c_module_free(&instance);
    wasm_rt_free();
    fclose(out);
    return 1;
  }

  if (len != 0 && fwrite(memory->data + ptr, 1, len, out) != len) {
    perror("fwrite");
    wasm2c_module_free(&instance);
    wasm_rt_free();
    fclose(out);
    return 1;
  }

  wasm2c_module_free(&instance);
  wasm_rt_free();
  fclose(out);
  return 0;
}
'''


def extract_payload() -> bytes:
    with tempfile.TemporaryDirectory(prefix="wasm-pipeline-") as tmpdir_name:
        tmpdir = Path(tmpdir_name)
        module_c = tmpdir / "module.c"
        payload_path = tmpdir / "payload.bin"
        runner_c = tmpdir / "runner.c"
        runner_bin = tmpdir / "runner"

        subprocess.run(
            ["wasm2c", "/app/module.wasm", "-n", "module", "-o", str(module_c)],
            check=True,
        )
        runner_c.write_text(RUNNER_C, encoding="utf-8")
        subprocess.run(
            [
                "gcc",
                "-O2",
                "-I",
                "/usr/include",
                str(runner_c),
                str(module_c),
                "/usr/share/wabt/wasm2c/wasm-rt-impl.c",
                "-o",
                str(runner_bin),
                "-lm",
            ],
            check=True,
        )
        subprocess.run([str(runner_bin), str(payload_path)], check=True)
        return payload_path.read_bytes()


def score_payload(payload: bytes) -> int:
    lib = ctypes.CDLL("/app/libcompute.so")
    lib.score_bytes.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.score_bytes.restype = ctypes.c_int64

    buf = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
    return int(lib.score_bytes(buf, len(payload)))


def main() -> None:
    payload = extract_payload()
    result = score_payload(payload)
    Path("/app/output.txt").write_text(f"{result}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
PY

cat <<'SH' >/app/run_pipeline.sh
#!/bin/bash
set -euo pipefail
python3 /app/run_pipeline.py
SH

chmod +x /app/run_pipeline.py /app/run_pipeline.sh
/app/run_pipeline.sh
