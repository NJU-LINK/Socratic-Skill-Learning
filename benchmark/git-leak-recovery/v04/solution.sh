#!/bin/bash
cd /app/repo

> /app/secret.txt

# Recover the secret from dangling git objects left by git stash drop
for hash in $(git fsck 2>/dev/null | grep "dangling commit" | awk '{print $3}'); do
    content=$(git diff-tree -p -m --no-commit-id "$hash" 2>/dev/null)
    if echo "$content" | grep -q 'secret\[' 2>/dev/null; then
        echo "$content" | grep -o 'secret\[[^]]*\]' > /app/secret.txt
        break
    fi
done

# Fallback: check dangling blobs
if [ ! -s /app/secret.txt ]; then
    for hash in $(git fsck 2>/dev/null | grep "dangling blob" | awk '{print $3}'); do
        content=$(git cat-file -p "$hash" 2>/dev/null)
        if echo "$content" | grep -q 'secret\[' 2>/dev/null; then
            echo "$content" | grep -o 'secret\[[^]]*\]' > /app/secret.txt
            break
        fi
    done
fi

# Permanently remove all traces
git reflog expire --expire=now --all
git gc --prune=now --aggressive 2>/dev/null
rm -rf .git/lost-found/ 2>/dev/null
