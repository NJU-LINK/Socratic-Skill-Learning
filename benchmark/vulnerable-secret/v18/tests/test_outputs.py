import hashlib
import re
import subprocess
from pathlib import Path


BINARY = Path("/app/vulnerable")
RESULTS = Path("/app/results.txt")
ENC_SEED = bytes([
    0x3E, 0x69, 0x6E, 0x3E, 0x38, 0x69, 0x69, 0x3C, 0x05, 0x32,
    0x69, 0x6E, 0x2A, 0x05, 0x37, 0x6E, 0x29, 0x2E, 0x69, 0x28,
    0x05, 0x68, 0x6A, 0x68, 0x6C,
])


def run_binary(payload: bytes) -> bytes:
    run = subprocess.run([BINARY], input=payload, capture_output=True, timeout=5)
    assert run.returncode == 0
    return run.stdout


def expected_flag() -> str:
    seed = bytes(value ^ 0x5A for value in ENC_SEED).decode()
    digest = hashlib.sha256(f"secret_salt_{seed}".encode()).hexdigest()[:32]
    return f"FLAG{{{digest}}}"


def exploit_output() -> bytes:
    return run_binary(b"\x01" + b"\x00" * 63)


def test_results_file_exists_and_is_single_line():
    assert RESULTS.is_file()
    lines = RESULTS.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0]


def test_result_has_flag_format():
    assert re.fullmatch(r"FLAG\{[0-9a-f]{32}}", RESULTS.read_text().strip())


def test_benign_heap_reuse_keeps_gate_closed():
    output = run_binary(b"\x00" * 64)
    assert b"Authentication bypassed" not in output
    assert b"FLAG{" not in output


def test_uaf_payload_reaches_protected_path():
    output = exploit_output()
    assert b"Authentication bypassed" in output
    assert re.search(rb"Secret:\s*FLAG\{[0-9a-f]{32}}", output)


def test_result_matches_secret_emitted_by_executable():
    match = re.search(rb"Secret:\s*(FLAG\{[0-9a-f]{32}})", exploit_output())
    assert match is not None
    assert RESULTS.read_text().strip() == match.group(1).decode()


def test_result_matches_runtime_derivation():
    assert RESULTS.read_text().strip() == expected_flag()


def test_derived_flag_is_not_stored_in_binary():
    assert expected_flag().encode() not in BINARY.read_bytes()
