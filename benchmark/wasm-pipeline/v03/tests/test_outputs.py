import ctypes
import shutil
import subprocess
from pathlib import Path


ROOT = Path("/app")
PIPELINE = ROOT / "run_pipeline.sh"


def run_pipeline() -> str:
    subprocess.run([str(PIPELINE)], check=True, cwd=ROOT)
    return ROOT.joinpath("output.txt").read_text(encoding="utf-8").strip()


def score_bytes(data: bytes, library_path: Path) -> int:
    library = ctypes.CDLL(str(library_path))
    library.score_bytes.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint32,
    ]
    library.score_bytes.restype = ctypes.c_int64
    buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    return int(library.score_bytes(buffer, len(data)))


def build_library(tmp_path: Path) -> Path:
    source_path = tmp_path / "fixture.c"
    library_path = tmp_path / "fixture.so"
    source_path.write_text(
        """
#include <stdint.h>

int64_t score_bytes(const uint8_t *data, uint32_t len)
{
    uint64_t h = 1469598103934665603ULL;
    for (uint32_t i = 0; i < len; ++i)
    {
        h ^= (uint64_t)data[i];
        h *= 1099511628211ULL;
    }

    __int128 t = ((__int128)((int64_t)h) * ((__int128)31337)) + ((__int128)2718281);
    int64_t y = (int64_t)t;
    return y ^ (int64_t)424242;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", str(source_path), "-o", str(library_path)],
        check=True,
    )
    return library_path


def build_static_fixture(
    tmp_path: Path, payload: bytes, offset: int
) -> tuple[Path, Path]:
    wat_path = tmp_path / "fixture_static.wat"
    wasm_path = tmp_path / "fixture_static.wasm"
    escaped = "".join(f"\\{byte:02x}" for byte in payload)
    wat_path.write_text(
        "\n".join(
            [
                "(module",
                '  (memory (export "mem") 1)',
                f'  (data (i32.const {offset}) "{escaped}")',
                '  (func (export "emit_ptr") (result i32)',
                f"    i32.const {offset})",
                '  (func (export "emit_len") (result i32)',
                f"    i32.const {len(payload)}))",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(["wat2wasm", str(wat_path), "-o", str(wasm_path)], check=True)
    return wasm_path, build_library(tmp_path)


def build_runtime_fixture(
    tmp_path: Path, payload: bytes, offset: int
) -> tuple[Path, Path]:
    wat_path = tmp_path / "fixture_runtime.wat"
    wasm_path = tmp_path / "fixture_runtime.wasm"
    stores = []
    for index, byte in enumerate(payload):
        stores.extend(
            [
                f"    i32.const {offset + index}",
                f"    i32.const {byte}",
                "    i32.store8",
            ]
        )
    wat_lines = [
        "(module",
        '  (memory (export "mem") 1)',
        "  (global $base (mut i32) (i32.const 0))",
        "  (func $init",
        *stores,
        f"    i32.const {offset}",
        "    global.set $base)",
        "  (start $init)",
        '  (func (export "emit_ptr") (result i32)',
        "    (local $tmp i32)",
        "    global.get $base",
        "    local.set $tmp",
        "    local.get $tmp",
        "    i32.const 0",
        "    i32.add)",
        '  (func (export "emit_len") (result i32)',
        "    (local $n i32)",
        "    i32.const 2",
        "    local.set $n",
        "    local.get $n",
        f"    i32.const {len(payload) - 2}",
        "    i32.add))",
    ]
    wat_path.write_text("\n".join(wat_lines), encoding="utf-8")
    subprocess.run(["wat2wasm", str(wat_path), "-o", str(wasm_path)], check=True)
    return wasm_path, build_library(tmp_path)


def install_fixture(wasm_path: Path, library_path: Path) -> None:
    shutil.copy2(wasm_path, ROOT / "module.wasm")
    shutil.copy2(library_path, ROOT / "libcompute.so")


def test_pipeline_artifact_matches_documented_sample() -> None:
    assert PIPELINE.is_file()
    assert PIPELINE.stat().st_mode & 0o111
    assert run_pipeline() == "-5176062472613077653"


def test_pipeline_uses_emit_len_and_score_bytes_on_generated_fixture(
    tmp_path: Path,
) -> None:
    payload = b"custom-length-fixture-data"
    wasm_path, library_path = build_static_fixture(tmp_path, payload, offset=1234)
    install_fixture(wasm_path, library_path)
    assert run_pipeline() == str(score_bytes(payload, library_path))


def test_pipeline_instantiates_wasm_and_observes_runtime_memory_effects(
    tmp_path: Path,
) -> None:
    payload = bytes([0, 1, 2, 250, 17, 99, 42])
    wasm_path, library_path = build_runtime_fixture(tmp_path, payload, offset=8192)
    install_fixture(wasm_path, library_path)
    assert run_pipeline() == str(score_bytes(payload, library_path))
