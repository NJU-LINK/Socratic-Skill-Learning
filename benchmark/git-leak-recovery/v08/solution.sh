#!/bin/bash

cd /app/repo

SUBMODULE="lib/secrets"

if [ ! -d "$SUBMODULE/.git" ] && [ ! -f "$SUBMODULE/.git" ]; then
    echo "ERROR: Submodule not found at $SUBMODULE"
    exit 1
fi

cd "$SUBMODULE"

GIT_DIR=$(git rev-parse --git-dir)

# Recover dangling objects
git fsck --lost-found 2>/dev/null

# Extract the secret from recovered objects
> /app/secret.txt

# Check lost-found commits (dangling commit case)
for f in "$GIT_DIR/lost-found/commit/"*; do
    [ -f "$f" ] || continue
    hash=$(basename "$f")
    if git show "$hash" 2>/dev/null | grep -q "secret\[[^]]*\]"; then
        git show "$hash" 2>/dev/null | grep -o "secret\[[^]]*\]" > /app/secret.txt
        break
    fi
done

# Fallback: check lost-found blobs (dangling blob case)
if [ ! -s /app/secret.txt ]; then
    for f in "$GIT_DIR/lost-found/other/"*; do
        [ -f "$f" ] || continue
        if grep -q "secret\[[^]]*\]" "$f" 2>/dev/null; then
            grep -o "secret\[[^]]*\]" "$f" > /app/secret.txt
            break
        fi
    done
fi

# Clean up submodule
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Remove lost-found copies
rm -rf "$GIT_DIR/lost-found/"

cd /app/repo
git reflog expire --expire=now --all

if [ -s /app/secret.txt ]; then
    echo "SUCCESS: Secret recovered and cleaned up!"
else
    echo "WARNING: No secret found!"
fi
