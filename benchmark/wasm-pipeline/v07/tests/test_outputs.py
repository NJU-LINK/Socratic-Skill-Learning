import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path


APP_DIR = Path("/app")
MODULE_PATH = APP_DIR / "module.wasm"
LIB_PATH = APP_DIR / "libcompute.so"
CONTRACT_PATH = APP_DIR / "contract.json"
OUTPUT_PATH = APP_DIR / "output.txt"
PIPELINE_PATH = APP_DIR / "run_pipeline.sh"
FIXED_LEN = 16


def _write_shared_library(tmp_path: Path, symbol_name: str) -> Path:
    c_path = tmp_path / "case.c"
    lib_path = tmp_path / "case.so"
    c_path.write_text(
        "\n".join(
            [
                "#include <stdint.h>",
                "",
                f"int64_t {symbol_name}(const uint8_t *data)",
                "{",
                f"    return (int64_t)data[{FIXED_LEN - 1}];",
                "}",
                "",
            ]
        )
    )
    subprocess.run(["gcc", "-shared", "-fPIC", "-O2", str(c_path), "-o", str(lib_path)], check=True)
    return lib_path


def _write_simple_case(tmp_path: Path, payload: bytes, names: dict[str, str]) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    escaped = "".join(f"\\{byte:02x}" for byte in payload)
    wat_path = tmp_path / "case.wat"
    wasm_path = tmp_path / "case.wasm"
    contract_path = tmp_path / "contract.json"

    wat_path.write_text(
        "\n".join(
            [
                "(module",
                f'  (memory (export "{names["memory_export"]}") 1)',
                f'  (data (i32.const 4096) "{escaped}")',
                f'  (func (export "{names["wasm_function"]}") (result i32)',
                "    i32.const 4096)",
                ")",
                "",
            ]
        )
    )
    subprocess.run(["wat2wasm", str(wat_path), "-o", str(wasm_path)], check=True)
    lib_path = _write_shared_library(tmp_path, names["so_symbol"])
    contract_path.write_text(json.dumps(names) + "\n")
    return wasm_path, lib_path, contract_path


def _write_runtime_initialized_case(tmp_path: Path, payload: bytes, names: dict[str, str]) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    wat_path = tmp_path / "runtime_case.wat"
    wasm_path = tmp_path / "runtime_case.wasm"
    contract_path = tmp_path / "contract.json"

    body_lines = [
        "(module",
        f'  (memory (export "{names["memory_export"]}") 1)',
        "  (global $ptr (mut i32) (i32.const 12288))",
        f'  (func (export "{names["wasm_function"]}") (result i32)',
        "    (local $tmp i32)",
        "    i32.const 111",
        "    local.set $tmp",
    ]
    for offset, byte in enumerate(payload):
        body_lines.extend(
            [
                "    global.get $ptr",
                f"    i32.const {offset}",
                "    i32.add",
                f"    i32.const {byte}",
                "    i32.store8",
            ]
        )
    body_lines.extend(
        [
            "    local.get $tmp",
            "    drop",
            "    global.get $ptr",
            ")",
            ")",
            "",
        ]
    )
    wat_path.write_text("\n".join(body_lines))
    subprocess.run(["wat2wasm", str(wat_path), "-o", str(wasm_path)], check=True)
    lib_path = _write_shared_library(tmp_path, names["so_symbol"])
    contract_path.write_text(json.dumps(names) + "\n")
    return wasm_path, lib_path, contract_path


def _write_start_initialized_case(tmp_path: Path, payload: bytes, names: dict[str, str]) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    wat_path = tmp_path / "start_case.wat"
    wasm_path = tmp_path / "start_case.wasm"
    contract_path = tmp_path / "contract.json"

    body_lines = [
        "(module",
        f'  (memory (export "{names["memory_export"]}") 1)',
        "  (global $base (mut i32) (i32.const 12280))",
        "  (func $init",
    ]
    for offset, byte in enumerate(payload):
        body_lines.extend(
            [
                "    global.get $base",
                f"    i32.const {offset}",
                "    i32.add",
                f"    i32.const {byte}",
                "    i32.store8",
            ]
        )
    body_lines.extend(
        [
            "  )",
            "  (start $init)",
            f'  (func (export "{names["wasm_function"]}") (result i32)',
            "    (local $tmp i32)",
            "    global.get $base",
            "    i32.const 8",
            "    i32.add",
            "    local.tee $tmp",
            "    global.set $base",
            "    local.get $tmp",
            "    i32.const 8",
            "    i32.sub",
            "  )",
            ")",
            "",
        ]
    )
    wat_path.write_text("\n".join(body_lines))
    subprocess.run(["wat2wasm", str(wat_path), "-o", str(wasm_path)], check=True)
    lib_path = _write_shared_library(tmp_path, names["so_symbol"])
    contract_path.write_text(json.dumps(names) + "\n")
    return wasm_path, lib_path, contract_path


@contextmanager
def _replace_app_files(module_path: Path, lib_path: Path, contract_path: Path):
    backup_dir = Path("/tmp") / f"wasm-pipeline-backup-{os.getpid()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups = {
        MODULE_PATH: backup_dir / MODULE_PATH.name,
        LIB_PATH: backup_dir / LIB_PATH.name,
        CONTRACT_PATH: backup_dir / CONTRACT_PATH.name,
    }
    for src, dst in backups.items():
        shutil.copy2(src, dst)

    shutil.copy2(module_path, MODULE_PATH)
    shutil.copy2(lib_path, LIB_PATH)
    shutil.copy2(contract_path, CONTRACT_PATH)
    OUTPUT_PATH.unlink(missing_ok=True)

    try:
        yield
    finally:
        for dst, src in backups.items():
            shutil.copy2(src, dst)
        shutil.rmtree(backup_dir, ignore_errors=True)
        OUTPUT_PATH.unlink(missing_ok=True)


def test_run_pipeline_exists_and_is_executable():
    assert PIPELINE_PATH.exists(), "/app/run_pipeline.sh was not created"
    assert os.access(PIPELINE_PATH, os.X_OK), "/app/run_pipeline.sh is not executable"


def test_sample_case_produces_expected_output():
    subprocess.run([str(PIPELINE_PATH)], check=True)
    assert OUTPUT_PATH.read_text().strip() == "33"


def test_randomized_contract_names_are_used(tmp_path):
    payload = bytes([17, 33, 99, 1, 4, 8, 16, 32, 64, 127, 128, 129, 200, 201, 202, 203])
    names = {"memory_export": "cells", "wasm_function": "dropoff", "so_symbol": "measure_block"}
    wasm_path, lib_path, contract_path = _write_simple_case(tmp_path / "simple", payload, names)
    with _replace_app_files(wasm_path, lib_path, contract_path):
        subprocess.run([str(PIPELINE_PATH)], check=True)
        assert OUTPUT_PATH.read_text().strip() == str(payload[-1])


def test_pipeline_executes_wasm_to_populate_memory(tmp_path):
    payload = bytes([91, 18, 220, 7, 44, 88, 130, 1, 55, 144, 233, 16, 72, 109, 250, 173])
    names = {"memory_export": "arena", "wasm_function": "reveal", "so_symbol": "mix_bytes"}
    wasm_path, lib_path, contract_path = _write_runtime_initialized_case(tmp_path / "runtime", payload, names)
    with _replace_app_files(wasm_path, lib_path, contract_path):
        subprocess.run([str(PIPELINE_PATH)], check=True)
        assert OUTPUT_PATH.read_text().strip() == str(payload[-1])


def test_pipeline_handles_start_and_additional_wasm_ops(tmp_path):
    payload = bytes([4, 8, 15, 16, 23, 42, 64, 91, 11, 19, 27, 35, 43, 51, 59, 67])
    names = {"memory_export": "heap", "wasm_function": "emit", "so_symbol": "score_bytes"}
    wasm_path, lib_path, contract_path = _write_start_initialized_case(tmp_path / "start", payload, names)
    with _replace_app_files(wasm_path, lib_path, contract_path):
        subprocess.run([str(PIPELINE_PATH)], check=True)
        assert OUTPUT_PATH.read_text().strip() == str(payload[-1])
