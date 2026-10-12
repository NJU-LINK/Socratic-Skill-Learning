#!/bin/bash
set -euo pipefail

cd /app/repo

REPLACE_HASHES=($(git replace -l 2>/dev/null))

if [ ${#REPLACE_HASHES[@]} -eq 0 ]; then
    for f in .git/refs/replace/*; do
        [ -f "$f" ] || continue
        REPLACE_HASHES+=("$(basename "$f")")
    done
fi

for orig_hash in "${REPLACE_HASHES[@]}"; do
    GIT_NO_REPLACE_OBJECTS=1 git show "$orig_hash" 2>/dev/null | grep -o 'secret\[[^]]*\]' > /app/secret.txt
    git replace -d "$orig_hash" 2>/dev/null || true
done

git reflog expire --expire=now --all
git gc --prune=now --aggressive 2>/dev/null

rm -rf /app/repo/.git/lost-found/

if [ -s /app/secret.txt ]; then
    echo "SUCCESS: Secret recovered and cleaned up!"
else
    echo "WARNING: No secret found!"
fi
