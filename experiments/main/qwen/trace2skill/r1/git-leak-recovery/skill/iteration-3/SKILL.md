---
name: git-leak-recovery
description: General starting point for solving tasks in the git-leak-recovery family.
---

# git-leak-recovery

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Workflow

### 1. Locate Leaked Content
When a file is staged (`git add`) and later removed from the index without being committed, its blob remains as an unreachable object.
```bash
# Find dangling blobs
git fsck --dangling --no-reflogs 2>&1 | grep 'dangling blob'
# Extract content
git cat-file -p <blob_hash>
```

### 2. Purge Unreachable Objects
Permanently remove dangling objects to ensure they cannot be recovered from loose storage, packfiles, or reflogs.
```bash
# Remove lost-found if created by fsck
rm -rf .git/lost-found
# Expire all reflogs immediately
git reflog expire --expire=now --all
# Prune all unreachable objects
git gc --prune=now --aggressive
```

### 3. Verify Secret Eradication
Do not rely solely on Git history commands. Scan the raw `.git/` directory and ensure no dangling objects remain.
```bash
# Confirm no dangling objects remain
git fsck --dangling --no-reflogs
# Confirm the purged blob hash is gone (should fail)
git cat-file -p <blob_hash>
# Scan raw git directory for the secret pattern
grep -r '<secret_pattern>' .git/
```
