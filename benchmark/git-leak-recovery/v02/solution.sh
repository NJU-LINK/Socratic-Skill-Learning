#!/bin/bash
set -euo pipefail

cd /app/repo

git fsck --lost-found 2>/dev/null

parts=()
for f in .git/lost-found/other/*; do
    parts+=("$(cat "$f")")
done

secret=""
for ((start=0; start<${#parts[@]}; start++)); do
    combined=""
    for ((i=start; i<${#parts[@]}+start; i++)); do
        idx=$((i % ${#parts[@]}))
        combined+="${parts[$idx]}"
    done
    candidate=$(echo "$combined" | grep -o 'secret\[[^]]*\]' || true)
    if [ -n "$candidate" ]; then
        secret="$candidate"
        break
    fi
done

echo "$secret" > /app/secret.txt

git reflog expire --expire=now --all
git gc --prune=now
rm -rf .git/lost-found
