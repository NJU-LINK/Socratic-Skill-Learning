import ctypes
import shutil
import subprocess
from pathlib import Path

import pytest


APP = Path("/app")


def run_pipeline() -> str:
    subprocess.run([str(APP / "run_pipeline.sh")], check=True, cwd=APP)
    return (APP / "output.txt").read_text(encoding="utf-8").strip()


def build_fixture(tmp_path: Path, payload: bytes, offset: int) -> int:
    escaped = "".join(f"\\{byte:02x}" for byte in payload)
    packed = (len(payload) << 32) | offset
    wat = tmp_path / "fixture.wat"
    wasm = tmp_path / "fixture.wasm"
    c_file = tmp_path / "fixture.c"
    library = tmp_path / "fixture.so"
    wat.write_text(
        "\n".join(
            [
                "(module",
                '  (memory (export "memory") 1)',
                f'  (data (i32.const {offset}) "{escaped}")',
                '  (func (export "produce_region") (result i64)',
                f"    i64.const {packed}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["wat2wasm", str(wat), "-o", str(wasm)], check=True)
    c_file.write_text(
        """
#include <stdint.h>
int64_t transform_region(const uint8_t *data, uint32_t len) {
    int64_t total = (int64_t)len * 1000 + 17;
    for (uint32_t i = 0; i < len; ++i) total = total * 131 + data[i];
    return total;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["gcc", "-shared", "-fPIC", "-O2", str(c_file), "-o", str(library)], check=True)
    shutil.copy2(wasm, APP / "module.wasm")
    shutil.copy2(library, APP / "libcompute.so")
    lib = ctypes.CDLL(str(library))
    lib.transform_region.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.transform_region.restype = ctypes.c_int64
    buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
    return int(lib.transform_region(buffer, len(payload)))


@pytest.fixture(autouse=True)
def restore_sample_inputs(tmp_path: Path):
    module_backup = tmp_path / "sample-module.wasm"
    library_backup = tmp_path / "sample-libcompute.so"
    shutil.copy2(APP / "module.wasm", module_backup)
    shutil.copy2(APP / "libcompute.so", library_backup)
    yield
    shutil.copy2(module_backup, APP / "module.wasm")
    shutil.copy2(library_backup, APP / "libcompute.so")


def test_pipeline_script_is_the_agent_artifact():
    pipeline = APP / "run_pipeline.sh"
    assert pipeline.is_file()
    assert pipeline.stat().st_mode & 0o111


def test_pipeline_matches_public_sample():
    assert run_pipeline() == "3991"


@pytest.mark.parametrize(
    "payload,offset",
    [
        (b"packed-region-check", 4096),
        (bytes([0, 255, 17, 0, 99, 128, 42]), 12345),
        (b"short", 2048),
    ],
)
def test_pipeline_unpacks_length_and_offset(payload: bytes, offset: int, tmp_path: Path):
    expected = build_fixture(tmp_path, payload, offset)
    assert run_pipeline() == str(expected)
