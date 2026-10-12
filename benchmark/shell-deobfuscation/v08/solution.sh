#!/bin/bash

SUS="/app/suspicious_script.sh"
CLEAN="/app/clean.sh"

grep '>> "$tmpf"' "$SUS" > /tmp/_real_lines
DECODED=$(mktemp)

while IFS= read -r line; do
  encoded=$(printf '%s' "$line" | sed -n 's/.*echo "\([^"]*\)"[[:space:]]*|.*/\1/p')
  [ -z "$encoded" ] && continue

  printf '%s' "$encoded" > /tmp/_chunk

  if printf '%s' "$line" | grep -q 'gunzip'; then
    cat /tmp/_chunk | base64 -d | gunzip | base64 -d >> "$DECODED"
  elif printf '%s' "$line" | grep -q 'xxd'; then
    cat /tmp/_chunk | xxd -r -p >> "$DECODED"
  elif printf '%s' "$line" | grep -q 'python3'; then
    cat /tmp/_chunk | base64 -d | python3 -c "
import sys
d = sys.stdin.buffer.read()
k = b'\xde\xad'
sys.stdout.buffer.write(bytes(d[i] ^ k[i % len(k)] for i in range(len(d))))
" | base64 -d >> "$DECODED"
  fi
done < /tmp/_real_lines

cp "$DECODED" "$CLEAN"
chmod -x "$SUS" "$CLEAN"
rm -f "$DECODED" /tmp/_chunk /tmp/_real_lines
