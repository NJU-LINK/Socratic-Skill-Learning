#!/bin/bash

cd /app/repo

# Recover the secret from the annotated tag
git show v0.1-experiment 2>/dev/null | grep -o 'secret\[[^]]*\]' | head -1 > /app/secret.txt

# Fallback: search through all tag contents
if [ ! -s /app/secret.txt ]; then
    git for-each-ref refs/tags/ --format='%(contents)' 2>/dev/null | grep -o 'secret\[[^]]*\]' | head -1 > /app/secret.txt
fi

# Delete the annotated tag referencing the secret
git tag -d v0.1-experiment 2>/dev/null || true

# Remove backup references
rm -f .git/ORIG_HEAD .git/FETCH_HEAD .git/MERGE_HEAD
rm -rf .git/refs/original

# Expire all reflog entries
git reflog expire --expire=now --all

# Prune all unreachable objects
git gc --prune=now --aggressive
