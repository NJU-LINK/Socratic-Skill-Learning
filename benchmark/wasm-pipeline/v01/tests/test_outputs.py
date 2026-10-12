import shutil
import subprocess
from pathlib import Path

import pytest


APP = Path("/app")


def run_pipeline() -> str:
    subprocess.run([str(APP / "run_pipeline.sh")], check=True, cwd=APP)
    return (APP / "output.txt").read_text(encoding="utf-8").strip()


def encode_uleb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(out)


def encode_sleb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        sign = byte & 0x40
        more = not ((value == 0 and not sign) or (value == -1 and sign))
        out.append(byte | 0x80 if more else byte)
        if not more:
            return bytes(out)


def section(section_id: int, payload: bytes) -> bytes:
    return bytes([section_id]) + encode_uleb(len(payload)) + payload


def name(value: str) -> bytes:
    raw = value.encode("utf-8")
    return encode_uleb(len(raw)) + raw


def module_with_payload(payload: bytes, offset: int = 4096) -> bytes:
    type_section = section(1, encode_uleb(1) + b"\x60\x00\x01\x7f")
    function_section = section(3, encode_uleb(2) + encode_uleb(0) + encode_uleb(0))
    memory_section = section(5, encode_uleb(1) + b"\x00\x01")
    export_section = section(
        7,
        b"".join(
            [
                encode_uleb(3),
                name("memory") + b"\x02" + encode_uleb(0),
                name("produce") + b"\x00" + encode_uleb(0),
                name("produce_len") + b"\x00" + encode_uleb(1),
            ]
        ),
    )
    pointer_body = encode_uleb(0) + b"\x41" + encode_sleb(offset) + b"\x0b"
    length_body = encode_uleb(0) + b"\x41" + encode_sleb(len(payload)) + b"\x0b"
    code_section = section(
        10,
        encode_uleb(2)
        + encode_uleb(len(pointer_body))
        + pointer_body
        + encode_uleb(len(length_body))
        + length_body,
    )
    data = (
        encode_uleb(1)
        + encode_uleb(0)
        + b"\x41"
        + encode_sleb(offset)
        + b"\x0b"
        + encode_uleb(len(payload))
        + payload
    )
    return (
        b"\x00asm\x01\x00\x00\x00"
        + type_section
        + function_section
        + memory_section
        + export_section
        + code_section
        + section(11, data)
    )


def module_with_start_initialized_payload(tmp_path: Path, payload: bytes, offset: int) -> bytes:
    stores = []
    for index, byte in enumerate(payload):
        stores.extend(
            [
                f"    i32.const {offset + index}",
                f"    i32.const {byte}",
                "    i32.store8",
            ]
        )
    wat = tmp_path / "runtime-payload.wat"
    wasm = tmp_path / "runtime-payload.wasm"
    wat.write_text(
        "\n".join(
            [
                "(module",
                '  (memory (export "memory") 1)',
                "  (func $initialize",
                *stores,
                "  )",
                "  (start $initialize)",
                '  (func (export "produce") (result i32)',
                f"    i32.const {offset})",
                '  (func (export "produce_len") (result i32)',
                f"    i32.const {len(payload)}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["wat2wasm", str(wat), "-o", str(wasm)], check=True)
    return wasm.read_bytes()


def expected(payload: bytes) -> int:
    value = 1469598103934665603
    for byte in payload:
        value ^= byte
        value = (value * 1099511628211) & ((1 << 64) - 1)
    return (value ^ len(payload)) % 257


@pytest.fixture(autouse=True)
def restore_sample_inputs(tmp_path: Path):
    module_backup = tmp_path / "module.wasm"
    library_backup = tmp_path / "libcompute.so"
    shutil.copy2(APP / "module.wasm", module_backup)
    shutil.copy2(APP / "libcompute.so", library_backup)
    yield
    shutil.copy2(module_backup, APP / "module.wasm")
    shutil.copy2(library_backup, APP / "libcompute.so")


def test_pipeline_script_is_the_agent_artifact():
    pipeline = APP / "run_pipeline.sh"
    assert pipeline.is_file()
    assert pipeline.stat().st_mode & 0o111


def test_sample_pipeline_output_matches_public_hint():
    assert run_pipeline() == "102"


@pytest.mark.parametrize(
    "payload,offset",
    [
        (b"abcdefg", 4096),
        (bytes([0, 255, 17, 0, 99, 128, 42]), 12345),
        (b"length-is-not-sixteen", 2048),
    ],
)
def test_pipeline_uses_exported_pointer_and_exact_length(payload: bytes, offset: int):
    (APP / "module.wasm").write_bytes(module_with_payload(payload, offset))
    assert run_pipeline() == str(expected(payload))


def test_pipeline_really_instantiates_wasm_and_observes_start_effects(tmp_path: Path):
    payload = bytes([0, 255, 17, 33, 91, 4, 5, 6, 201, 8, 9, 10, 11])
    (APP / "module.wasm").write_bytes(
        module_with_start_initialized_payload(tmp_path, payload, 7000)
    )
    assert run_pipeline() == str(expected(payload))
