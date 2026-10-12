import re
from pathlib import Path


OUTPUT = Path("/app/recovered_passwords.txt")
EXPECTED = "8XDA1B2C3D4E5F6G7H8W54"


def recovered_lines() -> list[str]:
    assert OUTPUT.is_file(), "Missing /app/recovered_passwords.txt"
    return [line.strip() for line in OUTPUT.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_output_contains_exactly_one_verified_candidate():
    assert len(recovered_lines()) == 1


def test_recovered_password_matches_public_shape_constraints():
    password = recovered_lines()[0]
    assert 20 <= len(password) <= 26
    assert password.startswith("8XD")
    assert password.endswith("W54")
    assert re.fullmatch(r"[A-Z0-9]+", password)


def test_crc_verified_password_is_recovered_exactly():
    assert recovered_lines() == [EXPECTED]
