#!/bin/bash

cd /app/repo

# Recover dangling blobs to .git/lost-found/other/
git fsck --lost-found 2>/dev/null

# Extract the secret from lost-found blob files
> /app/secret.txt
for blob in .git/lost-found/other/*; do
    [ -f "$blob" ] || continue
    if grep -q "secret\[[^]]*\]" "$blob" 2>/dev/null; then
        grep -o "secret\[[^]]*\]" "$blob" > /app/secret.txt 2>/dev/null
        break
    fi
done

# Clean up unreachable objects
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Remove the lost-found copies
rm -rf .git/lost-found/

# Verify
if [ -s /app/secret.txt ]; then
    echo "SUCCESS: Secret recovered and cleaned up!"
else
    echo "WARNING: No secret found!"
fi
