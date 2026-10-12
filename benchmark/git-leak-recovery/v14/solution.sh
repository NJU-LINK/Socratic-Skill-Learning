#!/bin/bash
set -euo pipefail

cd /app/repo

# 1. Find the secret in git history and save it
git log -p --all | grep -o 'secret\[[^]]*\]' | head -1 > /app/secret.txt

# 2. Rewrite history to remove secret.txt from all reachable commits
git filter-branch --force --tree-filter 'rm -f secret.txt' --prune-empty master

# 3. Remove backup refs created by filter-branch
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do
  git update-ref -d "$ref"
done

# 4. Delete the tag that pointed to a secret-containing commit
git tag -d v1.0 2>/dev/null || true

# 5. Remove backup reference files
rm -f .git/ORIG_HEAD .git/FETCH_HEAD

# 6. Expire all reflog entries
git reflog expire --expire=now --all

# 7. Prune all dangling objects
git gc --prune=now
