#!/bin/bash
set -euo pipefail

cd /app/repo

> /app/secret.txt

# Recover the secret from the reflog
# The amended commit's original (pre-amend) still exists in the reflog
git reflog --all | while read hash rest; do
    if git cat-file -e "$hash:secret.txt" 2>/dev/null; then
        content=$(git cat-file -p "$hash:secret.txt" 2>/dev/null) || true
        if [ -n "$content" ]; then
            secret=$(echo "$content" | grep -o "secret\[[^]]*\]" || true)
            if [ -n "$secret" ]; then
                echo "$secret" > /app/secret.txt
                break
            fi
        fi
    fi
done

# Clean up all unreachable objects
git reflog expire --expire=now --all
git gc --prune=now
