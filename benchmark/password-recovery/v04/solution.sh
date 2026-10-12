#!/bin/bash
set -euo pipefail

RECOVERED="/app/recovered_passwords.txt"
: > "$RECOVERED"

# Step 1: Find the disk image via config file (per variant design)
CONFIG="/app/cfg/volumes.conf"
if [ ! -f "$CONFIG" ]; then
  echo "Error: Config file $CONFIG not found" >&2
  exit 1
fi

DISK=$(grep "^data_volume=" "$CONFIG" | cut -d= -f2)
if [ -z "$DISK" ] || [ ! -f "$DISK" ]; then
  echo "Error: Disk image not found at '$DISK'" >&2
  exit 1
fi

# Step 2: Find fragment 1 start (PK\x03\x04 zip local header)
F1_DISK=$(od -A d -v -t x1 "$DISK" | grep " 50 4b 03 04" | head -1 | awk '{print $1}' | sed 's/^0*//')
F1_DISK=${F1_DISK:-0}
if [ -z "$F1_DISK" ]; then
  echo "Error: No zip PK header found in disk image" >&2
  exit 1
fi

# Step 3: Find PASSWORD= string position (inside fragment 1)
P_LINE=$(strings -t d "$DISK" | grep "PASSWORD=" | head -1)
P_DISK=$(echo "$P_LINE" | awk '{print $1}' | sed 's/^0*//')
P_DISK=${P_DISK:-0}
if [ -z "$P_DISK" ]; then
  echo "Error: Could not find PASSWORD= in disk image" >&2
  exit 1
fi

# Step 4: Calculate split points within the original zip
OFFSET_IN_ZIP=$((P_DISK - F1_DISK))
SPLIT1=$((OFFSET_IN_ZIP + 12))
SPLIT2=$((OFFSET_IN_ZIP + 22))

# Step 5: Extract fragment 1
FRAG1=$(mktemp)
FRAG2=$(mktemp)
FRAG3=$(mktemp)
trap 'rm -f "$FRAG1" "$FRAG2" "$FRAG3"' EXIT
dd if="$DISK" of="$FRAG1" bs=1 count="$SPLIT1" skip="$F1_DISK" 2>/dev/null

# Step 6: Use Python to find fragments 2 and 3, reassemble, extract password
python3 - "$DISK" "$SPLIT2" "$F1_DISK" "$SPLIT1" "$RECOVERED" "$FRAG1" "$FRAG2" "$FRAG3" << 'PYEOF'
import sys, struct, re, os

disk_path = sys.argv[1]
split2 = int(sys.argv[2])
pk_pos = int(sys.argv[3])
split1 = int(sys.argv[4])
output_path = sys.argv[5]
out_dir = os.path.dirname(output_path)
os.makedirs(out_dir, exist_ok=True)

frag1_path = sys.argv[6]
frag2_path = sys.argv[7]
frag3_path = sys.argv[8]

with open(disk_path, 'rb') as f:
    data = f.read()

# Find EOCD (PK\x05\x06) — search from end
eocd_pos = data.rfind(b'PK\x05\x06')
assert eocd_pos >= 0, "EOCD not found in disk image"

# Parse EOCD to get total zip size
cd_size = struct.unpack_from('<I', data, eocd_pos + 12)[0]
cd_offset = struct.unpack_from('<I', data, eocd_pos + 16)[0]
comment_len = struct.unpack_from('<H', data, eocd_pos + 20)[0]
total_zip = cd_offset + cd_size + 22 + comment_len

frag3_size = total_zip - split2
assert frag3_size > 0, f"Invalid fragment 3 size: {frag3_size}"

# Find fragment 3 start on disk
# The password tail after fragment 2 is 13 chars ending with "R63"
# Search for [A-Z0-9]+R63 and compute f3_start = match_end - 13
f3_start = None
for m in re.finditer(rb'[A-Z0-9]+R63', data):
    end = m.end()
    candidate = end - 13
    # Fragment 3 must contain the EOCD at position frag3_size - 22 within it
    if candidate + frag3_size >= eocd_pos:
        f3_start = candidate
    elif f3_start is None:
        f3_start = candidate

assert f3_start is not None, "Could not locate fragment 3 in disk image"
assert f3_start > 0 and f3_start + frag3_size <= len(data), \
    f"Fragment 3 out of bounds: {f3_start} + {frag3_size} > {len(data)}"

# Find fragment 2: standalone 10-byte [A-Z0-9] sequence, not in frag1 or frag3
f1_end = pk_pos + split1
f3_end = f3_start + frag3_size
f2_start = None

# Strategy 1: find exact [A-Z0-9]{10} with non-[A-Z0-9] boundaries
for i in range(len(data) - 10):
    chunk = data[i:i+10]
    ok = True
    for b in chunk:
        if not (48 <= b <= 57 or 65 <= b <= 90):
            ok = False
            break
    if not ok:
        continue
    # Check boundary before
    if i > 0:
        b = data[i-1]
        if 48 <= b <= 57 or 65 <= b <= 90:
            continue
    # Check boundary after
    if i + 10 < len(data):
        b = data[i+10]
        if 48 <= b <= 57 or 65 <= b <= 90:
            continue
    # Not in fragment 1 region
    if pk_pos <= i < f1_end:
        # Fragment 1 shouldn't have [A-Z0-9]{10}, but skip if it does
        continue
    # Not in fragment 3 region
    if f3_start <= i < f3_end:
        continue
    f2_start = i
    break

# Strategy 2 (fallback): if no exact match, find [A-Z0-9]{10,} not containing R63
if f2_start is None:
    for m in re.finditer(rb'[A-Z0-9]{10,}', data):
        start = m.start()
        text = data[start:m.end()]
        # Skip fragment 3's R63 sequence
        if b'R63' in text:
            continue
        # Skip fragment 1 region
        if pk_pos <= start < f1_end:
            continue
        # Skip fragment 3 region
        if f3_start <= start < f3_end:
            continue
        f2_start = start
        break

assert f2_start is not None, "Could not locate fragment 2 in disk image"

# Extract fragments 2 and 3
frag2_data = data[f2_start:f2_start + 10]
frag3_data = data[f3_start:f3_start + frag3_size]

with open(frag2_path, 'wb') as f:
    f.write(frag2_data)
with open(frag3_path, 'wb') as f:
    f.write(frag3_data)

# Reassemble the zip
zip_data = open(frag1_path, 'rb').read() + frag2_data + frag3_data

# Extract password from the reassembled zip
import zipfile, io
password = None

try:
    with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
        for name in z.namelist():
            content = z.read(name).decode('utf-8', errors='replace')
            m = re.search(r'PASSWORD=([A-Z0-9]+)', content)
            if m:
                password = m.group(1)
                break
except Exception:
    pass

if password is None:
    # Fallback: write zip to temp file and try unzip
    zip_path = os.path.join(os.path.dirname(frag1_path), 'reassembled.zip')
    with open(zip_path, 'wb') as f:
        f.write(zip_data)
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                content = z.read(name).decode('utf-8', errors='replace')
                m = re.search(r'PASSWORD=([A-Z0-9]+)', content)
                if m:
                    password = m.group(1)
                    break
    except Exception:
        pass

if password is not None:
    with open(output_path, 'w') as f:
        f.write(password + '\n')
    print(f"Recovered: {password}")
    sys.exit(0)
else:
    print("Error: Failed to extract password from reassembled zip", file=sys.stderr)
    sys.exit(1)
PYEOF

# Verify the result
if [ ! -s "$RECOVERED" ]; then
  echo "Error: Password recovery failed" >&2
  exit 1
fi

echo ""
cat "$RECOVERED"
