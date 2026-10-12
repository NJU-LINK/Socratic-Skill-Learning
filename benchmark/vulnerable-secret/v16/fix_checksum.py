#!/usr/bin/env python3
"""fix_checksum.py — Compute SHA-256 of the first executable LOAD segment
and patch it into the binary for runtime integrity verification.

The binary contains a 32-byte placeholder array (sequential bytes 0xA0..0xBF).
This script finds the placeholder, replaces it with SHA-256 of the text segment.
"""

import hashlib
import struct
import sys


PLACEHOLDER = bytes(range(0xA0, 0xC0))  # 0xA0 through 0xBF (32 bytes)

# ELF constants
PT_LOAD = 1
PF_X = 1


def find_executable_segment(data: bytes) -> tuple[int, int] | None:
    """Find (offset, filesz) of the first executable PT_LOAD segment."""
    if data[:4] != b'\x7fELF':
        return None

    is_64bit = data[4] == 2
    is_le = data[5] == 1
    if not is_64bit or not is_le:
        print("ERROR: only 64-bit little-endian ELF supported", file=sys.stderr)
        return None

    # ELF64 header
    e_phoff   = struct.unpack_from('<Q', data, 0x20)[0]
    e_phentsize = struct.unpack_from('<H', data, 0x36)[0]
    e_phnum     = struct.unpack_from('<H', data, 0x38)[0]

    for i in range(e_phnum):
        ph_off = e_phoff + i * e_phentsize
        p_type  = struct.unpack_from('<I', data, ph_off + 0x00)[0]
        p_flags = struct.unpack_from('<I', data, ph_off + 0x04)[0]
        p_offset = struct.unpack_from('<Q', data, ph_off + 0x08)[0]
        p_filesz = struct.unpack_from('<Q', data, ph_off + 0x20)[0]

        if p_type == PT_LOAD and (p_flags & PF_X):
            return (p_offset, p_filesz)

    return None


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <binary>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path, 'rb') as f:
        data = bytearray(f.read())

    result = find_executable_segment(data)
    if result is None:
        print("ERROR: executable LOAD segment not found", file=sys.stderr)
        sys.exit(1)

    seg_offset, seg_size = result
    print(f"Executable segment: offset=0x{seg_offset:x}, filesz={seg_size}")

    if seg_offset + seg_size > len(data):
        print("ERROR: segment extends beyond file", file=sys.stderr)
        sys.exit(1)

    seg_data = data[seg_offset:seg_offset + seg_size]
    computed_hash = hashlib.sha256(seg_data).digest()
    print(f"SHA-256(text segment): {computed_hash.hex()}")

    placeholder_off = data.find(PLACEHOLDER)
    if placeholder_off < 0:
        print("ERROR: placeholder pattern not found in binary", file=sys.stderr)
        sys.exit(1)
    print(f"Placeholder at file offset 0x{placeholder_off:x}")

    data[placeholder_off:placeholder_off + 32] = computed_hash
    print("Patched expected hash.")

    with open(path, 'wb') as f:
        f.write(data)

    print(f"Updated: {path}")


if __name__ == '__main__':
    main()
