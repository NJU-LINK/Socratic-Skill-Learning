#!/bin/bash
set -euo pipefail

NOTE_FILE="/app/NOTE_FROM_ATTACKER.txt"
RECOVERED_DIR="/app/recovered"
SEARCH_DIRS=("/app/sensitive_data" "/app/configs")

mkdir -p "$RECOVERED_DIR"

KEY_HEX=$(grep -oP 'Key:\s*0x([0-9A-Fa-f]+)' "$NOTE_FILE" | head -1 | grep -oP '0x[0-9A-Fa-f]+' || true)
if [ -z "$KEY_HEX" ]; then
    echo "Error: Could not extract XOR key from $NOTE_FILE"
    exit 1
fi

KEY_DEC=$((KEY_HEX))

for dir in "${SEARCH_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        continue
    fi
    while IFS= read -r -d '' filepath; do
        filename=$(basename "$filepath")
        case "$filename" in
            *~*) ;;
            *) continue ;;
        esac

        obfuscated_name="${filename%%~*}"
        hex_ext="${filename##*~}"

        if [ -z "$obfuscated_name" ] || [ -z "$hex_ext" ]; then
            continue
        fi

        if ! [[ "$obfuscated_name" =~ ^[0-9A-Fa-f]+$ ]] || ! [[ "$hex_ext" =~ ^[0-9A-Fa-f]+$ ]]; then
            continue
        fi

        python3 - "$filepath" "$obfuscated_name" "$hex_ext" "$KEY_DEC" "$RECOVERED_DIR" << 'PYEOF'
import sys, os

infile = sys.argv[1]
obfuscated_hex = sys.argv[2]
hex_ext = sys.argv[3]
key = int(sys.argv[4])
outdir = sys.argv[5]

orig_name_bytes = bytes(b ^ key for b in bytes.fromhex(obfuscated_hex))
orig_name = orig_name_bytes.decode('ascii')
ext_bytes = bytes.fromhex(hex_ext)
orig_ext = ext_bytes.decode('ascii')
full_name = f'{orig_name}.{orig_ext}'

with open(infile, 'rb') as f:
    data = f.read()

decoded = bytes(b ^ key for b in data)
outfile = os.path.join(outdir, full_name)

with open(outfile, 'wb') as f:
    f.write(decoded)

print(f'Recovered: {full_name}')
PYEOF
    done < <(find "$dir" -type f -print0)
done
