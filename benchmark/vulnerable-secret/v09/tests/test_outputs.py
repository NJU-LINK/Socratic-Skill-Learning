import re
import subprocess
from pathlib import Path


BINARY = Path("/app/vulnerable")
RESULTS = Path("/app/results.txt")
XOR_KEY = 0x42


def query(indices: list[int]) -> bytes:
    payload = "".join(f"{index}\n" for index in indices).encode()
    run = subprocess.run([BINARY], input=payload, capture_output=True, timeout=5)
    assert run.returncode == 0
    return run.stdout


def leaked_bytes() -> bytes:
    output = query(list(range(-38, 0)))
    values = [
        line[2]
        for line in output.split(b"\n")
        if line.startswith(b"> ") and len(line) == 3
    ]
    return bytes(values)


def extracted_secret() -> str:
    return bytes(value ^ XOR_KEY for value in leaked_bytes()).decode().rstrip("\x00")


def test_results_file_exists_and_is_single_line():
    assert RESULTS.is_file()
    lines = RESULTS.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0]


def test_result_has_flag_format():
    assert re.fullmatch(r"FLAG\{[^}\r\n]+}", RESULTS.read_text().strip())


def test_documented_nonnegative_indices_show_only_allowed_characters():
    output = query([0, 1, 61, -1])
    assert b"> 0\n" in output
    assert b"> 1\n" in output
    assert b"> z\n" in output
    assert b"FLAG{" not in output


def test_negative_index_sequence_discloses_encrypted_bytes():
    disclosed = leaked_bytes()
    assert len(disclosed) == 37
    assert b"FLAG{" not in disclosed


def test_disclosed_bytes_decode_to_flag():
    assert re.fullmatch(r"FLAG\{[^}\r\n]+}", extracted_secret())


def test_result_matches_decoded_executable_disclosure():
    assert RESULTS.read_text().strip() == extracted_secret()


def test_plaintext_result_is_not_stored_in_binary():
    assert RESULTS.read_text().strip().encode() not in BINARY.read_bytes()
