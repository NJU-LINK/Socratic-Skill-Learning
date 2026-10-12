import os
import pathlib

RECOVERED = pathlib.Path("/app/recovered")

EXPECTED_CONTENT = {
    "credentials.txt": """\
user: test_user
pass: P0$$wOrd123!
server: 192.168.1.100
""",
    "project_alpha.log": """\
Log entry 1: System initialized.
Log entry 2: User 'admin' logged in.
Log entry 3: Critical operation started.
""",
}


def test_recovered_directory_not_empty():
    assert RECOVERED.is_dir(), "/app/recovered does not exist"
    files = list(RECOVERED.iterdir())
    assert len(files) > 0, "/app/recovered is empty"


def test_expected_files_exist():
    for fname in EXPECTED_CONTENT:
        path = RECOVERED / fname
        assert path.is_file(), f"Expected file {fname} not found in /app/recovered"


def test_no_xor_files_in_recovered():
    xor_files = list(RECOVERED.glob("*.xor"))
    assert len(xor_files) == 0, f".xor files found in /app/recovered: {xor_files}"


def test_credentials_content():
    path = RECOVERED / "credentials.txt"
    assert path.is_file(), "credentials.txt not found"
    actual = path.read_text()
    expected = EXPECTED_CONTENT["credentials.txt"]
    assert actual.strip() == expected.strip(), (
        f"credentials.txt content mismatch.\n"
        f"Expected:\n{expected}\nGot:\n{actual}"
    )


def test_project_alpha_log_content():
    path = RECOVERED / "project_alpha.log"
    assert path.is_file(), "project_alpha.log not found"
    actual = path.read_text()
    expected = EXPECTED_CONTENT["project_alpha.log"]
    assert actual.strip() == expected.strip(), (
        f"project_alpha.log content mismatch.\n"
        f"Expected:\n{expected}\nGot:\n{actual}"
    )


def test_only_expected_files():
    files = {f.name for f in RECOVERED.iterdir()}
    expected = set(EXPECTED_CONTENT.keys())
    unknown = files - expected
    assert not unknown, f"Unexpected files in /app/recovered: {unknown}"


def test_no_obfuscation_artifact():
    for fname in EXPECTED_CONTENT:
        path = RECOVERED / fname
        data = path.read_bytes()
        assert b".xor" not in data, f"Obfuscation artifact found in {fname}"
