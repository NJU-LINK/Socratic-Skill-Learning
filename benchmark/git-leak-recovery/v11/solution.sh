#!/bin/bash
set -euo pipefail

cd /app/repo

TAG="v1.0rc"

git show "${TAG}:secret.txt" > /tmp/secret_tmp.txt
cp /tmp/secret_tmp.txt /app/secret.txt

git tag -d "$TAG"

rm -f .git/ORIG_HEAD .git/FETCH_HEAD

git reflog expire --expire=now --all

git gc --prune=now

git fsck --no-dangling > /dev/null 2>&1
