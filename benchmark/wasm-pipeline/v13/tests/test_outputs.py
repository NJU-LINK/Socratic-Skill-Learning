import random
import subprocess
from pathlib import Path


APP = Path("/app")
PIPELINE = APP / "run_pipeline.sh"


def run(command):
    return subprocess.run(command, check=True, text=True, capture_output=True)


def u32(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def s32(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        sign_bit_set = byte & 0x40
        done = (value == 0 and not sign_bit_set) or (value == -1 and sign_bit_set)
        if done:
            out.append(byte)
            return bytes(out)
        out.append(byte | 0x80)


def section(section_id: int, payload: bytes) -> bytes:
    return bytes([section_id]) + u32(len(payload)) + payload


def encode_name(name: str) -> bytes:
    raw = name.encode("utf-8")
    return u32(len(raw)) + raw


def i32_const(value: int) -> bytes:
    return b"\x41" + s32(value)


def make_stateful_wasm(data: bytes, base: int = 4096) -> bytes:
    assert len(data) == 16
    placeholder = b"." * len(data)
    seed_state_ops = bytearray()
    for index, value in enumerate(data):
        seed_state_ops.extend(i32_const(base + index))
        seed_state_ops.extend(i32_const(value))
        seed_state_ops.append(0x3A)
        seed_state_ops.extend(b"\x00\x00")
    seed_state_ops.append(0x0B)

    produce_ops = bytearray(i32_const(base))
    produce_ops.append(0x0B)
    type_section = section(
        1,
        u32(2) + b"\x60\x00\x00" + b"\x60\x00\x01\x7F",
    )
    function_section = section(3, u32(2) + u32(0) + u32(1))
    memory_section = section(5, u32(1) + b"\x00" + u32(1))
    exports = [
        encode_name("memory") + b"\x02" + u32(0),
        encode_name("seed_state") + b"\x00" + u32(0),
        encode_name("produce") + b"\x00" + u32(1),
    ]
    export_section = section(7, u32(len(exports)) + b"".join(exports))
    code_section = section(
        10,
        u32(2)
        + u32(1 + len(seed_state_ops))
        + b"\x00"
        + bytes(seed_state_ops)
        + u32(1 + len(produce_ops))
        + b"\x00"
        + bytes(produce_ops),
    )
    data_segment = (
        b"\x00"
        + i32_const(base)
        + b"\x0B"
        + u32(len(placeholder))
        + placeholder
    )
    data_section = section(11, u32(1) + data_segment)
    return (
        b"\x00asm\x01\x00\x00\x00"
        + type_section
        + function_section
        + memory_section
        + export_section
        + code_section
        + data_section
    )


def compile_shared_library(source: str) -> None:
    source_path = APP / "test_transform.c"
    source_path.write_text(source, encoding="utf-8")
    run(
        [
            "gcc",
            "-shared",
            "-fPIC",
            "-O2",
            str(source_path),
            "-o",
            str(APP / "libcompute.so"),
        ]
    )


def fnv1a64(data: bytes) -> int:
    value = 1469598103934665603
    for byte in data:
        value ^= byte
        value = (value * 1099511628211) & ((1 << 64) - 1)
    return value - (1 << 64) if value & (1 << 63) else value


def expected_value(data: bytes, multiplier: int, addend: int, xor_value: int) -> int:
    value = (fnv1a64(data) * multiplier + addend) & ((1 << 64) - 1)
    if value & (1 << 63):
        value -= 1 << 64
    mask = xor_value & ((1 << 64) - 1)
    if mask & (1 << 63):
        mask -= 1 << 64
    return value ^ mask


def run_pipeline() -> str:
    run([str(PIPELINE)])
    return (APP / "output.txt").read_text(encoding="utf-8").strip()


def write_case(
    data: bytes,
    multiplier: int,
    addend: int,
    xor_value: int,
    base: int = 4096,
) -> None:
    (APP / "module.wasm").write_bytes(make_stateful_wasm(data, base=base))
    compile_shared_library(
        f"""
#include <stdint.h>

int64_t transform(const uint8_t* data) {{
    uint64_t h = 1469598103934665603ULL;
    for (uint64_t i = 0; i < 16; ++i) {{
        h ^= (uint64_t)data[i];
        h *= 1099511628211ULL;
    }}
    __int128 t = ((__int128)((int64_t)h) * ((__int128){multiplier}))
               + ((__int128){addend});
    int64_t y = (int64_t)t;
    return y ^ (int64_t){xor_value};
}}
"""
    )


def test_pipeline_artifact_solves_public_sample():
    assert PIPELINE.is_file()
    assert PIPELINE.stat().st_mode & 0o111
    assert run_pipeline() == "33"


def test_pipeline_calls_seed_state_before_reading_memory():
    payload = b"stateful-output!"
    placeholder = b"................"
    write_case(payload, 1, 0, 0)
    actual = run_pipeline()
    assert actual == str(fnv1a64(payload))
    assert actual != str(fnv1a64(placeholder))


def test_randomized_regenerated_cases():
    rng = random.Random(1337)
    for _ in range(4):
        data = bytes(rng.randrange(0, 256) for _ in range(16))
        multiplier = rng.randrange(1, 1 << 16) * rng.choice([1, -1])
        addend = rng.randrange(-(1 << 31), 1 << 31)
        xor_value = rng.randrange(-(1 << 31), 1 << 31)
        write_case(data, multiplier, addend, xor_value)
        assert run_pipeline() == str(
            expected_value(data, multiplier, addend, xor_value)
        )
