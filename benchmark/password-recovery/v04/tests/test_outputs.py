import os
import re

PASSWORDS_PATH = "/app/recovered_passwords.txt"
PREFIX = "K9M"
SUFFIX = "R63"
EXPECTED_LENGTH = 26
CHARSET_PATTERN = re.compile(r'^[A-Z0-9]+$')

EXPECTED_PASSWORD = "K9MHG8T4LQ7BP2XFW5DVN0AR63"


def _read_passwords():
    assert os.path.exists(PASSWORDS_PATH), f"{PASSWORDS_PATH} not found"
    with open(PASSWORDS_PATH) as f:
        passwords = [line.strip() for line in f if line.strip()]
    assert len(passwords) > 0, f"{PASSWORDS_PATH} is empty"
    return passwords


def test_passwords_found():
    passwords = _read_passwords()
    assert len(passwords) >= 1, "No passwords were recovered"


def test_password_length():
    passwords = _read_passwords()
    for p in passwords:
        assert len(p) == EXPECTED_LENGTH, f"Password '{p}' has length {len(p)}, expected {EXPECTED_LENGTH}"


def test_password_prefix():
    passwords = _read_passwords()
    for p in passwords:
        assert p.startswith(PREFIX), f"Password '{p}' does not start with '{PREFIX}'"


def test_password_suffix():
    passwords = _read_passwords()
    for p in passwords:
        assert p.endswith(SUFFIX), f"Password '{p}' does not end with '{SUFFIX}'"


def test_password_charset():
    passwords = _read_passwords()
    for p in passwords:
        assert CHARSET_PATTERN.fullmatch(p), f"Password '{p}' contains characters outside [A-Z0-9]"


def test_no_false_positives():
    passwords = _read_passwords()
    for p in passwords:
        assert len(p) == EXPECTED_LENGTH
        assert p.startswith(PREFIX)
        assert p.endswith(SUFFIX)
        assert CHARSET_PATTERN.fullmatch(p)


def test_correct_password():
    passwords = _read_passwords()
    assert passwords[0] == EXPECTED_PASSWORD, f"Expected '{EXPECTED_PASSWORD}', got '{passwords[0]}'"


def test_only_one_password():
    passwords = _read_passwords()
    assert len(passwords) == 1, f"Expected exactly 1 password, found {len(passwords)}: {passwords}"
