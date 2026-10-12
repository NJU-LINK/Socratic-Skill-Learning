import hashlib
import re
from pathlib import Path


PASSWORD_FILE = Path("/app/recovered_passwords.txt")
CHECKSUM_FILE = Path("/app/checksum.txt")
EXPECTED_SHA256 = "efdd0da32c3114d25602dc4318d707bdc5ecdaf1c32a00cc71e2fb6c80d20ebf"
PREFIX = "8XD"
EXACT_LENGTH = 23


def passwords() -> list[str]:
    assert PASSWORD_FILE.exists(), f"{PASSWORD_FILE} does not exist"
    values = [line.strip() for line in PASSWORD_FILE.read_text().splitlines() if line.strip()]
    assert values, "recovered_passwords.txt is empty"
    return values


def test_recovered_passwords_exists():
    assert passwords()


def test_password_format():
    for password in passwords():
        assert len(password) == EXACT_LENGTH
        assert password.startswith(PREFIX)
        assert re.fullmatch(r"[A-Z0-9]+", password)


def test_password_matches_xor_checksum():
    expected = int(CHECKSUM_FILE.read_text().strip().split()[0])
    for password in passwords():
        checksum = 0
        for character in password:
            checksum ^= ord(character)
        assert checksum ^ 0xFF == expected


def test_exact_recovery_without_false_positives():
    digests = {
        hashlib.sha256(password.encode()).hexdigest()
        for password in passwords()
    }
    assert digests == {EXPECTED_SHA256}
