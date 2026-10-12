import hashlib
import re
import subprocess
from pathlib import Path


BINARY = Path("/app/vulnerable")
RESULTS = Path("/app/results.txt")
PASSWORD = "s3cur3_p4ss_2025_login_k3y"
QUERY_TOKEN = "m4g1c_qu3ry_t0k3n_r3pl_h4ck"
ADMIN_CODE = "4dm1n_c0d3_br34k_2025_r3pl"
SEED = "inject_th3_s33d_2o25_ch41n_h4sh_g3n"


def run_session(lines: list[str]) -> str:
    run = subprocess.run(
        [BINARY],
        input=("\n".join(lines) + "\n").encode(),
        capture_output=True,
        timeout=5,
    )
    assert run.returncode == 0
    return run.stdout.decode(errors="replace")


def expected_flag() -> str:
    value = SEED.encode()
    for _ in range(1000):
        value = hashlib.sha256(value).digest()
    return f"FLAG{{{value.hex()}}}"


def test_results_file_exists_and_is_single_line():
    assert RESULTS.is_file()
    lines = RESULTS.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0]


def test_result_has_64_hex_flag_format():
    assert re.fullmatch(r"FLAG\{[0-9a-f]{64}}", RESULTS.read_text().strip())


def test_wrong_login_does_not_disclose_seed():
    output = run_session(["login", "wrong-password", "exit"])
    assert "Authentication failed." in output
    assert "Seed value:" not in output


def test_admin_state_requires_query_verification():
    output = run_session(["login", PASSWORD, "admin", "logout", "exit"])
    assert "Complete query verification first." in output
    assert "Seed value:" not in output


def test_complete_state_sequence_discloses_expected_seed():
    output = run_session([
        "login",
        PASSWORD,
        "query",
        QUERY_TOKEN,
        "admin",
        ADMIN_CODE,
        "info",
        "exit",
    ])
    assert "Login successful." in output
    assert "Query authenticated." in output
    assert "Admin access granted." in output
    assert f"Seed value: {SEED}" in output


def test_result_matches_hash_chain_derived_from_disclosed_seed():
    assert RESULTS.read_text().strip() == expected_flag()


def test_derived_flag_is_not_stored_in_binary():
    assert expected_flag().encode() not in BINARY.read_bytes()
