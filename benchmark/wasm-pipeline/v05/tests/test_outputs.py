import pathlib
import subprocess


APP = pathlib.Path("/app")
PIPELINE = APP / "run_pipeline.sh"


def u32_leb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def i32_leb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        sign_bit = byte & 0x40
        done = (value == 0 and sign_bit == 0) or (value == -1 and sign_bit != 0)
        if done:
            out.append(byte)
            return bytes(out)
        out.append(byte | 0x80)


def i64_leb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        sign_bit = byte & 0x40
        done = (value == 0 and sign_bit == 0) or (value == -1 and sign_bit != 0)
        if done:
            out.append(byte)
            return bytes(out)
        out.append(byte | 0x80)


def wasm_section(section_id: int, payload: bytes) -> bytes:
    return bytes([section_id]) + u32_leb(len(payload)) + payload


def wasm_name(name: str) -> bytes:
    encoded = name.encode("utf-8")
    return u32_leb(len(encoded)) + encoded


def build_module(data_offset: int, payload: bytes, runtime_write: bool) -> bytes:
    packed = (len(payload) << 32) | data_offset
    type_section = wasm_section(1, u32_leb(1) + b"\x60\x00\x01\x7e")
    function_section = wasm_section(3, u32_leb(1) + u32_leb(0))
    memory_section = wasm_section(5, u32_leb(1) + u32_leb(0) + u32_leb(1))

    export_payload = bytearray()
    export_payload += u32_leb(2)
    export_payload += wasm_name("mem0") + b"\x02" + u32_leb(0)
    export_payload += wasm_name("produce_packed") + b"\x00" + u32_leb(0)
    export_section = wasm_section(7, bytes(export_payload))

    instructions = bytearray()
    if runtime_write:
        for index, byte in enumerate(payload):
            instructions += b"\x41" + i32_leb(data_offset + index)
            instructions += b"\x41" + i32_leb(byte)
            instructions += b"\x3a\x00\x00"
    instructions += b"\x42" + i64_leb(packed)
    instructions += b"\x0b"
    body = u32_leb(0) + bytes(instructions)
    code_section = wasm_section(10, u32_leb(1) + u32_leb(len(body)) + body)

    sections = [
        type_section,
        function_section,
        memory_section,
        export_section,
        code_section,
    ]
    if not runtime_write:
        data_expr = b"\x41" + i32_leb(data_offset) + b"\x0b"
        data_payload = (
            u32_leb(1)
            + u32_leb(0)
            + data_expr
            + u32_leb(len(payload))
            + payload
        )
        sections.append(wasm_section(11, data_payload))
    return b"\x00asm\x01\x00\x00\x00" + b"".join(sections)


def write_transform(path: pathlib.Path, expected_len: int):
    source = f"""
#include <stdint.h>

int64_t transform(const uint8_t *data)
{{
    uint64_t acc = 0;
    for (uint64_t i = 0; i < {expected_len}ULL; ++i) {{
        acc = acc * 131ULL + (uint64_t)data[i];
    }}
    return (int64_t)(acc - 5000);
}}
"""
    source_path = path.with_suffix(".c")
    source_path.write_text(source, encoding="utf-8")
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", str(source_path), "-o", str(path)],
        check=True,
    )


def expected_value(payload: bytes) -> int:
    accumulator = 0
    for byte in payload:
        accumulator = ((accumulator * 131) + byte) & 0xFFFFFFFFFFFFFFFF
    accumulator = (accumulator - 5000) & 0xFFFFFFFFFFFFFFFF
    return accumulator - (1 << 64) if accumulator >= (1 << 63) else accumulator


def run_case(payload: bytes, offset: int, runtime_write: bool = False) -> str:
    (APP / "module.wasm").write_bytes(build_module(offset, payload, runtime_write))
    write_transform(APP / "libcompute.so", len(payload))
    subprocess.run([str(PIPELINE)], cwd=APP, check=True)
    return (APP / "output.txt").read_text(encoding="utf-8").strip()


def test_pipeline_artifact_exists_and_is_executable():
    assert PIPELINE.is_file()
    assert PIPELINE.stat().st_mode & 0o111


def test_pipeline_reads_mem0_from_packed_pointer_and_length():
    payload = b"packed-pointer-demo"
    assert run_case(payload, 4096) == str(expected_value(payload))


def test_pipeline_uses_dynamic_length_not_fixed_sample_size():
    payload = b"short"
    assert run_case(payload, 1234) == str(expected_value(payload))


def test_pipeline_requires_real_runtime_instantiation_for_memory_contents():
    payload = b"runtime-written-bytes"
    assert run_case(payload, 777, runtime_write=True) == str(expected_value(payload))
