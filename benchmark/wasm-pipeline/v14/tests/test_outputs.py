import shutil
import subprocess
from pathlib import Path

import pytest


APP = Path("/app")


def run(command):
    return subprocess.run(command, check=True, text=True, capture_output=True)


def run_pipeline() -> str:
    run([str(APP / "run_pipeline.sh")])
    return (APP / "output.txt").read_text(encoding="utf-8").strip()


def compile_library(tmp_path: Path, weighted: bool) -> Path:
    source = tmp_path / "transform.c"
    library = tmp_path / "libcompute.so"
    body = (
        "int64_t total = 321; "
        "for (int i = 0; i < 16; ++i) total += (int64_t)(i + 5) * data[i]; "
        "return total;"
        if weighted
        else "return (int64_t)data[15];"
    )
    source.write_text(
        f"#include <stdint.h>\nint64_t crunch(const uint8_t *data) {{ {body} }}\n",
        encoding="utf-8",
    )
    run(["gcc", "-shared", "-fPIC", "-O2", str(source), "-o", str(library)])
    return library


def build_module(
    tmp_path: Path,
    payload: bytes,
    offset: int,
    base: int,
    start_initialized: bool,
) -> Path:
    delta = base ^ offset
    wat = tmp_path / "module.wat"
    wasm = tmp_path / "module.wasm"
    if start_initialized:
        stores = []
        for index, byte in enumerate(payload):
            stores.extend(
                [
                    f"    i32.const {offset + index}",
                    f"    i32.const {byte}",
                    "    i32.store8",
                ]
            )
        lines = [
            "(module",
            '  (memory (export "heap") 1)',
            "  (global $base (mut i32) (i32.const 0))",
            "  (global $delta (mut i32) (i32.const 0))",
            "  (func $initialize",
            *stores,
            f"    i32.const {base}",
            "    global.set $base",
            f"    i32.const {delta}",
            "    global.set $delta)",
            "  (start $initialize)",
            '  (func (export "get_base") (result i32) global.get $base)',
            '  (func (export "get_delta") (result i32) global.get $delta))',
        ]
    else:
        escaped = "".join(f"\\{byte:02x}" for byte in payload)
        lines = [
            "(module",
            '  (memory (export "heap") 1)',
            f'  (data (i32.const {offset}) "{escaped}")',
            '  (func (export "get_base") (result i32)',
            f"    i32.const {base})",
            '  (func (export "get_delta") (result i32)',
            f"    i32.const {delta}))",
        ]
    wat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run(["wat2wasm", str(wat), "-o", str(wasm)])
    return wasm


def install_case(tmp_path: Path, payload: bytes, offset: int, base: int, start_initialized: bool, weighted: bool):
    shutil.copy2(build_module(tmp_path, payload, offset, base, start_initialized), APP / "module.wasm")
    shutil.copy2(compile_library(tmp_path, weighted), APP / "libcompute.so")


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


@pytest.mark.parametrize(
    "payload,offset,base",
    [
        (b"0123456789abcdef", 4352, 23040),
        (bytes(range(16)), 8192, 0x4567),
        (bytes([255, 0, 17, 33, 9, 201, 88, 71, 6, 5, 4, 3, 2, 1, 0, 144]), 12345, 0x7312),
    ],
)
def test_pipeline_uses_xor_offset_and_exact_16_bytes(payload: bytes, offset: int, base: int, tmp_path: Path):
    install_case(tmp_path, payload, offset, base, False, False)
    assert run_pipeline() == str(payload[15])


def test_pipeline_honors_start_initialized_memory(tmp_path: Path):
    payload = bytes([11, 22, 33, 44, 55, 66, 77, 88, 99, 111, 123, 135, 147, 159, 171, 183])
    install_case(tmp_path, payload, 0x1200, 0x4567, True, True)
    expected = 321 + sum((index + 5) * byte for index, byte in enumerate(payload))
    assert run_pipeline() == str(expected)
