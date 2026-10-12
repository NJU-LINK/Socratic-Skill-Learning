#!/bin/bash
set -euo pipefail

RECOVERED_DIR="/app/recovered"
MANIFEST="/app/MANIFEST.txt"
SENSITIVE_DIR="/app/sensitive_data"

mkdir -p "$RECOVERED_DIR"

decode_b64_hex() {
    python3 -c "
import sys, base64
data = sys.stdin.buffer.read().strip()
hex_str = base64.b64decode(data).decode('ascii')
sys.stdout.buffer.write(bytes.fromhex(hex_str))
"
}

while IFS= read -r obfuscated_name; do
    [ -z "$obfuscated_name" ] && continue

    found=$(find "$SENSITIVE_DIR" -type f -name "$obfuscated_name" -print -quit)
    if [ -z "$found" ]; then
        echo "Error: obfuscated file '$obfuscated_name' not found under $SENSITIVE_DIR"
        exit 1
    fi

    original_path=$(printf '%s' "$obfuscated_name" | decode_b64_hex)
    original_name=$(basename "$original_path")

    decode_b64_hex < "$found" > "$RECOVERED_DIR/$original_name"

    echo "Recovered: $original_name"
done < "$MANIFEST"
