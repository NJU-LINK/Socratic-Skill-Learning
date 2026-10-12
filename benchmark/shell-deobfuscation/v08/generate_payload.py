#!/usr/bin/env python3
"""Generate deterministic multipart obfuscation with interleaved decoys."""

import base64
import gzip
import os
import random
import string


PAYLOAD = r"""#!/bin/bash
echo "System audit completed successfully."
hostname > /tmp/audit_trail.txt
whoami >> /tmp/audit_trail.txt
cat /etc/os-release >> /tmp/audit_trail.txt
echo c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2 >> /tmp/audit_trail.txt
rm -- "$0"
exit 0
"""

XOR_KEY = b"\xde\xad"
NUM_DECOY_VARS = 4
RNG = random.Random(20260726)


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode()


def gzipe(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


def hexe(data: bytes) -> str:
    return data.hex()


def xore(data: bytes, key: bytes = XOR_KEY) -> bytes:
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))


def random_garbage(length: int) -> bytes:
    return bytes(RNG.randint(0, 255) for _ in range(length))


def random_var_name() -> str:
    return "v_" + "".join(RNG.choices(string.ascii_letters, k=5))


def encode_part1(data: bytes) -> str:
    """Three layers: base64, gzip, base64."""
    return b64e(gzipe(b64e(data).encode()))


def encode_part2(data: bytes) -> str:
    """One hex layer."""
    return hexe(data)


def encode_part3(data: bytes) -> str:
    """Three transforms: base64, repeated-key XOR, base64."""
    return b64e(xore(b64e(data).encode()))


def decode_cmd_part1() -> str:
    return "base64 -d | gunzip | base64 -d 2>/dev/null"


def decode_cmd_part2() -> str:
    return "xxd -r -p 2>/dev/null"


def decode_cmd_part3() -> str:
    return (
        'base64 -d | python3 -c "import sys;d=sys.stdin.buffer.read();'
        'k=b\'\\\\xde\\\\xad\';sys.stdout.buffer.write(bytes(d[i]^k[i%len(k)] '
        "for i in range(len(d))))\" | base64 -d 2>/dev/null"
    )


def generate_decoy(pattern: int) -> tuple[str, str]:
    garbage = random_garbage(RNG.randint(15, 40))
    if pattern == 0:
        return encode_part1(garbage), decode_cmd_part1()
    if pattern == 1:
        return encode_part2(garbage), decode_cmd_part2()
    return encode_part3(garbage), decode_cmd_part3()


def build_script() -> str:
    RNG.seed(20260726)
    payload_lines = PAYLOAD.splitlines(True)
    first_split = len(payload_lines) // 3
    second_split = 2 * len(payload_lines) // 3
    parts = [
        "".join(payload_lines[:first_split]).encode(),
        "".join(payload_lines[first_split:second_split]).encode(),
        "".join(payload_lines[second_split:]).encode(),
    ]
    real_chunks = [
        (encode_part1(parts[0]), decode_cmd_part1()),
        (encode_part2(parts[1]), decode_cmd_part2()),
        (encode_part3(parts[2]), decode_cmd_part3()),
    ]
    decoys = [
        (random_var_name(), generate_decoy(index % 3))
        for index in range(NUM_DECOY_VARS)
    ]

    lines = ["#!/bin/bash", ""]
    for variable, (encoded, decoder) in decoys:
        lines.append(f'{variable}=$(echo "{encoded}" | {decoder})')
    lines.extend(["", "tmpf=$(mktemp)"])
    for encoded, decoder in real_chunks:
        lines.append(
            f'printf \'%s\\n\' "$(echo "{encoded}" | {decoder})" >> "$tmpf"'
        )
    lines.extend(['exec /bin/bash "$tmpf"', ""])
    return "\n".join(lines) + "\n"


def main() -> None:
    script = build_script()
    output = "/app/suspicious_script.sh"
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(output, 0o755)
    print(f"Generated obfuscated script: {output} ({len(script)} bytes)")


if __name__ == "__main__":
    main()
