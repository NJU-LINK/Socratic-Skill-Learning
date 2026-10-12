import re
from pathlib import Path

RESULT_PATH = Path("/app/results.txt")
BINARY_PATH = Path("/app/vulnerable")

RC4_KEY_LEN = 16
ENCRYPTED_SECRET_LEN = 32

# Known byte patterns of the key and encrypted secret as compiled into
# .rodata. Used to locate them at any file offset so the cross-check is
# architecture-independent (no hard-coded x86 section offsets).
RC4_KEY_BYTES = bytes([
    0x73, 0x33, 0x63, 0x72, 0x33, 0x74, 0x5f, 0x73,
    0x74, 0x72, 0x33, 0x34, 0x6d, 0x5f, 0x6b, 0x33
])
ENCRYPTED_SECRET_BYTES = bytes([
    0x9b, 0x52, 0xd7, 0x4f, 0x51, 0xbd, 0x1a, 0x6a, 0x5f, 0xe8, 0x6d, 0xe2,
    0x80, 0x1e, 0x6c, 0x94, 0x84, 0x3a, 0xc0, 0x59, 0xd8, 0xc4, 0x48, 0x65,
    0x82, 0x48, 0x14, 0x02, 0xf2, 0xc5, 0xba, 0x63
])


def rc4_crypt(key: bytes, data: bytes) -> bytes:
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]

    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        out.append(byte ^ S[(S[i] + S[j]) % 256])
    return bytes(out)


def get_expected_flag() -> str:
    """Independently decrypt the secret from the binary to cross-verify."""
    data = BINARY_PATH.read_bytes()
    key_pos = data.find(RC4_KEY_BYTES)
    assert key_pos != -1, "Could not locate RC4 key in binary"
    enc_pos = data.find(ENCRYPTED_SECRET_BYTES)
    assert enc_pos != -1, "Could not locate encrypted secret in binary"
    key = data[key_pos : key_pos + RC4_KEY_LEN]
    encrypted = data[enc_pos : enc_pos + ENCRYPTED_SECRET_LEN]
    decrypted = rc4_crypt(key, encrypted)
    text = decrypted.decode("ascii")
    match = re.search(r"FLAG\{[^}]+\}", text)
    assert match is not None, f"Could not decrypt flag from binary, got: {text}"
    return match.group(0)


EXPECTED_FLAG = get_expected_flag()


def test_result_file_exists():
    assert RESULT_PATH.exists(), f"results.txt not found at {RESULT_PATH}"


def test_result_not_empty():
    content = RESULT_PATH.read_text().strip()
    assert len(content) > 0, "results.txt is empty"


def test_result_is_flag_format():
    content = RESULT_PATH.read_text().strip()
    assert re.match(r"^FLAG\{[^}]+\}$", content), f"Invalid flag format: {content}"


def test_result_is_correct_flag():
    content = RESULT_PATH.read_text().strip()
    assert content == EXPECTED_FLAG, (
        f"Expected {EXPECTED_FLAG} (cross-verified from binary), got: {content}"
    )
