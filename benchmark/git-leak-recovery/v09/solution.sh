#!/bin/bash
set -euo pipefail

cd /app/repo

# Recover dangling objects (commits from deleted feature-secret branch)
git fsck --lost-found 2>/dev/null

# Search all blobs in dangling commits for the secret
for f in .git/lost-found/commit/*; do
    [ -f "$f" ] || continue
    h=$(basename "$f")
    git ls-tree -r "$h" 2>/dev/null | awk '{print $3}' | while read b; do
        git cat-file -p "$b" 2>/dev/null | grep -o "secret\[[^]]*\]" || true
    done
done > /app/secret.txt

# Clean up unreachable objects
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Remove the lost-found copies
rm -rf .git/lost-found/

[ -s /app/secret.txt ] && echo "SUCCESS: Secret recovered and cleaned up!" || echo "WARNING: No secret found!"
