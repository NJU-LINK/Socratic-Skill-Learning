import subprocess
from pathlib import Path


APP_DIR = Path("/app")
MODULE = APP_DIR / "module.wasm"
LIB = APP_DIR / "libcompute.so"
RUN_PIPELINE = APP_DIR / "run_pipeline.sh"
OUTPUT = APP_DIR / "output.txt"


def run(cmd):
    subprocess.run(cmd, check=True)


def encode_u32(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode_i32(value):
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


def make_section(section_id, payload):
    return bytes([section_id]) + encode_u32(len(payload)) + payload


def make_type_section():
    func_type = b"\x60\x00\x01\x7f"
    return make_section(1, encode_u32(1) + func_type)


def make_function_section(type_index_count):
    payload = encode_u32(type_index_count) + b"".join(
        encode_u32(0) for _ in range(type_index_count)
    )
    return make_section(3, payload)


def make_memory_section():
    return make_section(5, encode_u32(1) + b"\x00" + encode_u32(1))


def make_export_section(exported_function_index):
    memory_export = encode_u32(6) + b"memory" + b"\x02" + encode_u32(0)
    produce_export = (
        encode_u32(7) + b"produce" + b"\x00" + encode_u32(exported_function_index)
    )
    return make_section(7, encode_u32(2) + memory_export + produce_export)


def make_code_section(bodies):
    payload = encode_u32(len(bodies))
    for body in bodies:
        payload += encode_u32(len(body)) + body
    return make_section(10, payload)


def make_data_section(offset, data):
    payload = (
        encode_u32(1)
        + encode_u32(0)
        + b"\x41"
        + encode_i32(offset)
        + b"\x0b"
        + encode_u32(len(data))
        + data
    )
    return make_section(11, payload)


def write_literal_module(data, offset=4096):
    body = encode_u32(0) + b"\x41" + encode_i32(offset) + b"\x0b"
    module = (
        b"\x00asm\x01\x00\x00\x00"
        + make_type_section()
        + make_function_section(1)
        + make_memory_section()
        + make_export_section(0)
        + make_code_section([body])
        + make_data_section(offset, data)
    )
    MODULE.write_bytes(module)


def write_dynamic_module(data, offset=2048):
    helper_body = encode_u32(0) + b"\x41" + encode_i32(offset) + b"\x0b"
    produce_body = (
        encode_u32(0)
        + b"\x10"
        + encode_u32(0)
        + b"\x41"
        + encode_i32(0)
        + b"\x6a"
        + b"\x0b"
    )
    module = (
        b"\x00asm\x01\x00\x00\x00"
        + make_type_section()
        + make_function_section(2)
        + make_memory_section()
        + make_export_section(1)
        + make_code_section([helper_body, produce_body])
        + make_data_section(offset, data)
    )
    MODULE.write_bytes(module)


def write_library(weights, bias):
    weights_expr = ", ".join(str(weight) for weight in weights)
    source = f"""
#include <stdint.h>

int32_t fold_bytes(const uint8_t *data)
{{
    static const int32_t weights[16] = {{{weights_expr}}};
    int64_t total = {bias};
    for (int i = 0; i < 16; ++i)
    {{
        total += (int64_t)weights[i] * (int64_t)data[i];
    }}
    return (int32_t)total;
}}
"""
    source_path = APP_DIR / "test_transform.c"
    source_path.write_text(source, encoding="utf-8")
    run(["gcc", "-shared", "-fPIC", "-O2", str(source_path), "-o", str(LIB)])


def expected_value(data, weights, bias):
    total = bias
    for byte, weight in zip(data, weights):
        total += byte * weight
    total &= 0xFFFFFFFF
    if total & 0x80000000:
        total -= 0x100000000
    return total


def pipeline_result():
    run([str(RUN_PIPELINE)])
    return int(OUTPUT.read_text(encoding="utf-8").strip())


def test_pipeline_artifact_solves_public_sample_contract():
    assert RUN_PIPELINE.is_file()
    assert RUN_PIPELINE.stat().st_mode & 0o111
    data = bytes(
        [
            0x00,
            0x7F,
            0x80,
            0xFF,
            0x01,
            0x02,
            0x03,
            0x04,
            0x05,
            0x06,
            0x07,
            0x08,
            0x09,
            0x0A,
            0x0B,
            0xD6,
        ]
    )
    write_literal_module(data)
    write_library([1] * 16, -832)
    assert pipeline_result() == -42


def test_pipeline_handles_unsigned_bytes_and_signed_int32_return():
    data = bytes(
        [
            0x00,
            0x7F,
            0x80,
            0xFF,
            0x10,
            0x20,
            0x30,
            0x40,
            0xF0,
            0xEE,
            0xDD,
            0xCC,
            0xBB,
            0xAA,
            0x99,
            0x88,
        ]
    )
    weights = [
        7000000,
        -11000000,
        9000000,
        -5000000,
        3333333,
        -4444444,
        5555555,
        -6666666,
        7777777,
        -8888888,
        9999999,
        -1234567,
        2345678,
        -3456789,
        4567890,
        -5678901,
    ]
    bias = -200000000
    write_literal_module(data)
    write_library(weights, bias)
    assert pipeline_result() == expected_value(data, weights, bias)


def test_pipeline_executes_dynamic_produce_instead_of_static_parsing():
    data = bytes(
        [
            0xF1,
            0x80,
            0x00,
            0x01,
            0xFE,
            0x7E,
            0x55,
            0xAA,
            0x10,
            0x20,
            0x30,
            0x40,
            0xDE,
            0xAD,
            0xBE,
            0xEF,
        ]
    )
    weights = [1, 2, 3, 4, 5, 6, 7, 8, -9, -10, 11, 12, -13, 14, -15, 16]
    bias = -123456789
    write_dynamic_module(data, offset=1234)
    write_library(weights, bias)
    assert pipeline_result() == expected_value(data, weights, bias)
