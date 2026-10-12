#!/bin/bash
set -euo pipefail

RECOVERED="/app/recovered_passwords.txt"
> "$RECOVERED"

DISK_DIR="/app/varsea/disks/sub1"
if [ ! -d "$DISK_DIR" ]; then
  echo "Error: Disk directory $DISK_DIR not found" >&2
  exit 1
fi

shopt -s nullglob
dat_files=("$DISK_DIR"/*.dat)
shopt -u nullglob

if [ ${#dat_files[@]} -eq 0 ]; then
  echo "Error: No .dat files found in $DISK_DIR" >&2
  exit 1
fi

found=0
for f in "${dat_files[@]}"; do
  strs=$(strings "$f" 2>/dev/null) || continue

  frag1=$(echo "$strs" | grep -oE '8XD[A-Z0-9]+' | head -1 || true)
  frag2=$(echo "$strs" | grep -oE '[A-Z0-9]+W54' | head -1 || true)

  if [ -n "$frag1" ] && [ -n "$frag2" ]; then
    password="${frag1}${frag2}"
    if [ ${#password} -eq 23 ] && [[ "$password" =~ ^8XD[A-Z0-9]+W54$ ]]; then
      if ! grep -qxF "$password" "$RECOVERED" 2>/dev/null; then
        echo "$password" >> "$RECOVERED"
        found=1
      fi
    fi
  fi
done

if [ "$found" -eq 0 ]; then
  echo "Error: No valid password found in any disk image" >&2
  exit 1
fi

echo "Recovered passwords:"
cat "$RECOVERED"
