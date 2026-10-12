#!/bin/bash
set -euo pipefail

cd /app/repo

# Recover the secret from ORIG_HEAD (backup ref from aborted merge)
git show ORIG_HEAD:credentials.txt 2>/dev/null | grep -o 'secret\[[^]]*\]' > /app/secret.txt

# Remove the ORIG_HEAD ref that points to the secret commit
git update-ref -d ORIG_HEAD 2>/dev/null || true

# Expire all reflog entries so gc can prune
git reflog expire --expire=now --all

# Prune all unreachable objects
git gc --prune=now --aggressive

# Verify
if [ -s /app/secret.txt ]; then
    echo "SUCCESS: Secret recovered and cleaned up!"
else
    echo "WARNING: No secret found!"
fi
