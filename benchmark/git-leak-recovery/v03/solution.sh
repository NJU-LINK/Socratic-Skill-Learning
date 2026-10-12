#!/bin/bash
set -euo pipefail

cd /app/repo

git stash show -p stash@{0} | grep -o 'secret\[[^]]*\]' > /app/secret.txt

git stash drop
git reflog expire --expire=now --all
git gc --prune=now
