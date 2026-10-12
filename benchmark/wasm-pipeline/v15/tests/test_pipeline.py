from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


APP_DIR = Path("/app")
MODULE_PATH = APP_DIR / "module.wasm"
LIB_PATH = APP_DIR / "libcompute.so"
SEED_PATH = APP_DIR / "seed.bin"
OUTPUT_PATH = APP_DIR / "output.txt"
PIPELINE_PATH = APP_DIR / "run_pipeline.sh"


def run_pipeline() -> str:
    subprocess.run([str(PIPELINE_PATH)], check=True)
    return OUTPUT_PATH.read_text(encoding="utf-8").strip()


@pytest.fixture
def preserve_assets(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    for path in (MODULE_PATH, LIB_PATH, SEED_PATH):
        shutil.copy2(path, backup_dir / path.name)
    yield
    for path in (MODULE_PATH, LIB_PATH, SEED_PATH):
        shutil.copy2(backup_dir / path.name, path)
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()


def build_custom_module_wat() -> str:
    lines = [
        "(module",
        '  (memory (export "memory") 1)',
        '  (global $ready (mut i32) (i32.const 0))',
        '  (func (export "init") (param $seed_ptr i32)',
    ]
    for i in range(12):
        lines.append(
            f"    (i32.store8 (i32.add (i32.const 3000) (i32.const {i})) "
            f"(i32.xor (i32.load8_u (i32.add (local.get $seed_ptr) (i32.const {i}))) "
            f"(i32.const {40 + i})))"
        )
    for j in range(4):
        lines.append(
            f"    (i32.store8 (i32.add (i32.const 3012) (i32.const {j})) "
            f"(i32.and (i32.add "
            f"(i32.load8_u (i32.add (local.get $seed_ptr) (i32.const {8 + j}))) "
            f"(i32.const {90 + j})) (i32.const 255)))"
        )
    lines.append(
        "    (i32.store8 (i32.const 3015) "
        "(i32.xor (i32.load8_u (i32.add (local.get $seed_ptr) (i32.const 16))) "
        "(i32.const 171)))"
    )
    lines.extend(
        [
            '    (global.set $ready (i32.const 1)))',
            '  (func (export "produce") (result i32)',
            '    (if (i32.eqz (global.get $ready)) (then unreachable))',
            '    (i32.const 3000))',
            ')',
        ]
    )
    return "\n".join(lines)


def build_custom_transform_c() -> str:
    return textwrap.dedent(
        """
        #include <stdint.h>

        int64_t transform(const uint8_t *data)
        {
            int64_t total = -12;
            for (int i = 0; i < 16; ++i)
            {
                total += (int64_t)(i + 3) * data[i];
            }
            return total;
        }
        """
    ).strip()


def expected_custom_result(seed: bytes) -> int:
    derived = bytearray(16)
    for i in range(12):
        derived[i] = seed[i] ^ (40 + i)
    for j in range(4):
        derived[12 + j] = (seed[8 + j] + 90 + j) & 0xFF
    derived[15] = seed[16] ^ 171
    return sum((index + 3) * value for index, value in enumerate(derived)) - 12


def test_run_pipeline_exists_and_is_executable() -> None:
    assert PIPELINE_PATH.exists(), "/app/run_pipeline.sh was not created"
    assert PIPELINE_PATH.stat().st_mode & 0o111, "/app/run_pipeline.sh is not executable"


def test_sample_assets_produce_documented_output(preserve_assets: Path) -> None:
    assert run_pipeline() == "1876"


def test_pipeline_handles_replaced_assets(preserve_assets: Path, tmp_path: Path) -> None:
    seed = bytes([0, 255, 1, 127, 64, 32, 16, 8, 7, 6, 5, 4, 3, 2, 1, 0, 99])
    work_dir = tmp_path / "custom"
    work_dir.mkdir()

    wat_path = work_dir / "custom.wat"
    wasm_path = work_dir / "custom.wasm"
    c_path = work_dir / "custom.c"
    so_path = work_dir / "libcompute.so"

    wat_path.write_text(build_custom_module_wat(), encoding="utf-8")
    c_path.write_text(build_custom_transform_c(), encoding="utf-8")

    subprocess.run(["wat2wasm", str(wat_path), "-o", str(wasm_path)], check=True)
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", str(c_path), "-o", str(so_path)],
        check=True,
    )

    shutil.copy2(wasm_path, MODULE_PATH)
    shutil.copy2(so_path, LIB_PATH)
    SEED_PATH.write_bytes(seed)

    assert run_pipeline() == str(expected_custom_result(seed))
