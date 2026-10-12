#!/bin/bash
set -euo pipefail

cd /app/repo

git log -g -p | grep -o 'secret\[[^]]*\]' | head -1 > /app/secret.txt

if [ ! -s /app/secret.txt ]; then
  echo "ERROR: Secret not found" >&2
  exit 1
fi

git reflog expire --expire=now --all
git gc --prune=now --aggressive
