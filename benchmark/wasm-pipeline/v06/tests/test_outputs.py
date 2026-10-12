import ctypes
import struct
import subprocess
from pathlib import Path

import wasmtime


MODULE_PATH = Path("/app/module.wasm")
LIB_PATH = Path("/app/libcompute.so")
OUTPUT_PATH = Path("/app/output.txt")
RUN_PIPELINE_PATH = Path("/app/run_pipeline.sh")


def decode_payload_runtime(module_path: Path) -> tuple[int, bytes, bytes]:
    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    module = wasmtime.Module(engine, module_path.read_bytes())
    instance = wasmtime.Instance(store, module, [])
    exports = instance.exports(store)

    header_offset = int(exports["produce"](store))
    memory = exports["memory"]
    header = bytes(memory.read(store, header_offset, header_offset + 8))
    assert len(header) == 8, "produce() must point at a readable 8-byte header"

    payload_offset, payload_length = struct.unpack("<II", header)
    payload = bytes(memory.read(store, payload_offset, payload_offset + payload_length))
    assert len(payload) == payload_length, "payload range must be readable from wasm memory"
    return header_offset, header, payload


def transform_bytes(payload: bytes, library_path: Path) -> str:
    library = ctypes.CDLL(str(library_path))
    library.transform.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
    library.transform.restype = ctypes.c_uint64
    buffer = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
    return str(int(library.transform(buffer, len(payload))))


def expected_output(module_path: Path, library_path: Path) -> tuple[str, str]:
    _, header_bytes, payload = decode_payload_runtime(module_path)
    return transform_bytes(payload, library_path), transform_bytes(
        header_bytes, library_path
    )


def write_runtime_initialized_module(module_path: Path) -> None:
    wat = r"""(module
  (memory (export "memory") 1)
  (global $header_base (mut i32) (i32.const 80))
  (func $init
    i32.const 80
    i32.const 200
    i32.store
    i32.const 84
    i32.const 6
    i32.store
    i32.const 200
    i32.const 10
    i32.store8
    i32.const 201
    i32.const 20
    i32.store8
    i32.const 202
    i32.const 30
    i32.store8
    i32.const 203
    i32.const 40
    i32.store8
    i32.const 204
    i32.const 50
    i32.store8
    i32.const 205
    i32.const 60
    i32.store8)
  (start $init)
  (func (export "produce") (result i32)
    global.get $header_base
    i32.const 16
    i32.add
    i32.const 16
    i32.sub))"""
    module_path.write_bytes(bytes(wasmtime.wat2wasm(wat)))


def run_pipeline() -> str:
    subprocess.run([str(RUN_PIPELINE_PATH)], check=True)
    return OUTPUT_PATH.read_text(encoding="utf-8").strip()


def test_pipeline_artifact_exists_and_is_executable() -> None:
    assert RUN_PIPELINE_PATH.is_file()
    assert RUN_PIPELINE_PATH.stat().st_mode & 0o111


def test_pipeline_decodes_payload_instead_of_passing_header() -> None:
    expected, wrong = expected_output(MODULE_PATH, LIB_PATH)
    actual = run_pipeline()
    assert actual == expected
    assert actual != wrong, "pipeline must pass the decoded payload, not header bytes"


def test_pipeline_uses_runtime_wasm_execution_for_memory_and_produce() -> None:
    original_module = MODULE_PATH.read_bytes()
    try:
        write_runtime_initialized_module(MODULE_PATH)
        expected, wrong = expected_output(MODULE_PATH, LIB_PATH)
        actual = run_pipeline()
        assert actual == expected
        assert actual != wrong, "pipeline must decode the runtime-produced header"
    finally:
        MODULE_PATH.write_bytes(original_module)
