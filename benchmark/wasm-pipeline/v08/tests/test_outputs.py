import random
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


def fnv1a64(data: bytes) -> int:
    value = 1469598103934665603
    for byte in data:
        value ^= byte
        value = (value * 1099511628211) & ((1 << 64) - 1)
    return value - (1 << 64) if value & (1 << 63) else value


def expected(data: bytes, multiplier: int, addend: int, xor_value: int) -> int:
    value = (fnv1a64(data) * multiplier + addend) & ((1 << 64) - 1)
    value = value - (1 << 64) if value & (1 << 63) else value
    mask = xor_value & ((1 << 64) - 1)
    mask = mask - (1 << 64) if mask & (1 << 63) else mask
    return value ^ mask


def build_case(
    tmp_path: Path,
    payload: bytes,
    split: int,
    first_offset: int,
    second_offset: int,
    descriptor_offset: int,
    multiplier: int,
    addend: int,
    xor_value: int,
) -> None:
    first, second = payload[:split], payload[split:]
    descriptor = (
        first_offset.to_bytes(4, "little")
        + len(first).to_bytes(4, "little")
        + second_offset.to_bytes(4, "little")
        + len(second).to_bytes(4, "little")
    )
    escape = lambda value: "".join(f"\\{byte:02x}" for byte in value)
    wat = tmp_path / "case.wat"
    wasm = tmp_path / "case.wasm"
    source = tmp_path / "case.c"
    library = tmp_path / "case.so"
    wat.write_text(
        "\n".join(
            [
                "(module",
                '  (memory (export "memory") 1)',
                f'  (data (i32.const {first_offset}) "{escape(first)}")',
                f'  (data (i32.const {second_offset}) "{escape(second)}")',
                f'  (data (i32.const {descriptor_offset}) "{escape(descriptor)}")',
                '  (func (export "descriptor") (result i32)',
                f"    i32.const {descriptor_offset}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    run(["wat2wasm", str(wat), "-o", str(wasm)])
    source.write_text(
        f"""
#include <stddef.h>
#include <stdint.h>
int64_t transform(const uint8_t *data, size_t len) {{
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < len; ++i) {{ h ^= data[i]; h *= 1099511628211ULL; }}
    __int128 value = (__int128)((int64_t)h) * ({multiplier}) + ({addend});
    return ((int64_t)value) ^ ((int64_t){xor_value});
}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    run(["gcc", "-shared", "-fPIC", "-O2", str(source), "-o", str(library)])
    shutil.copy2(wasm, APP / "module.wasm")
    shutil.copy2(library, APP / "libcompute.so")


def build_start_initialized_case(
    tmp_path: Path,
    payload: bytes,
    split: int,
    first_offset: int,
    second_offset: int,
    descriptor_offset: int,
    multiplier: int,
    addend: int,
    xor_value: int,
) -> None:
    build_case(
        tmp_path,
        payload,
        split,
        first_offset,
        second_offset,
        descriptor_offset,
        multiplier,
        addend,
        xor_value,
    )
    first, second = payload[:split], payload[split:]
    descriptor_values = [first_offset, len(first), second_offset, len(second)]
    stores = []
    for base, chunk in ((first_offset, first), (second_offset, second)):
        for index, byte in enumerate(chunk):
            stores.extend(
                [
                    f"    i32.const {base + index}",
                    f"    i32.const {byte}",
                    "    i32.store8",
                ]
            )
    for index, value in enumerate(descriptor_values):
        stores.extend(
            [
                f"    i32.const {descriptor_offset + 4 * index}",
                f"    i32.const {value}",
                "    i32.store",
            ]
        )
    wat = tmp_path / "runtime-case.wat"
    wasm = tmp_path / "runtime-case.wasm"
    wat.write_text(
        "\n".join(
            [
                "(module",
                '  (memory (export "memory") 1)',
                "  (func $initialize",
                *stores,
                "  )",
                "  (start $initialize)",
                '  (func (export "descriptor") (result i32)',
                f"    i32.const {descriptor_offset}))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    run(["wat2wasm", str(wat), "-o", str(wasm)])
    shutil.copy2(wasm, APP / "module.wasm")


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


def test_sample_files_produce_public_value():
    assert run_pipeline() == "-5382930286282350554"


@pytest.mark.parametrize("seed", [1337, 2026, 9001, 65537])
def test_randomized_two_slice_cases(seed: int, tmp_path: Path):
    rng = random.Random(seed)
    payload = bytes(rng.randrange(0, 256) for _ in range(rng.randrange(8, 40)))
    split = rng.randrange(1, len(payload))
    first_offset = rng.choice([2048, 3072, 4096])
    second_offset = first_offset + rng.choice([80, 256, 640])
    descriptor_offset = rng.choice([1024, 1536, 1792])
    multiplier = rng.randrange(1, 1 << 16) * rng.choice([1, -1])
    addend = rng.randrange(-(1 << 31), 1 << 31)
    xor_value = rng.randrange(-(1 << 31), 1 << 31)
    build_case(
        tmp_path,
        payload,
        split,
        first_offset,
        second_offset,
        descriptor_offset,
        multiplier,
        addend,
        xor_value,
    )
    assert run_pipeline() == str(expected(payload, multiplier, addend, xor_value))


def test_pipeline_concatenates_both_segments_in_order(tmp_path: Path):
    payload = bytes(range(16))
    build_case(tmp_path, payload, 7, 4096, 4736, 1600, 1, 0, 0)
    actual = run_pipeline()
    assert actual == str(fnv1a64(payload))
    assert actual != str(fnv1a64(payload[:7]))
    assert actual != str(fnv1a64(payload[7:]))


def test_pipeline_instantiates_wasm_before_reading_descriptor_and_slices(tmp_path: Path):
    payload = bytes([255, 0, 17, 33, 9, 201, 88, 71, 6, 5, 4, 3, 2, 1, 0, 144])
    build_start_initialized_case(
        tmp_path,
        payload,
        5,
        5000,
        7000,
        1200,
        -37,
        911,
        0x123456,
    )
    assert run_pipeline() == str(expected(payload, -37, 911, 0x123456))
