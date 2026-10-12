---
name: git-leak-recovery
description: General starting point for solving tasks in the git-leak-recovery family.
---

# git-leak-recovery

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Core Workflow: Unreachable Staged Blobs Recovery and Purge

### 1. Locate and Extract Dangling Blobs
When a file is staged (`git add`) and removed from the index without committing, it remains as an unreachable blob.
- Identify the hash: `git fsck --unreachable --no-reflogs 2>&1 | grep 'unreachable blob'` (or `git fsck --dangling`)
- Extract content: `git cat-file -p <blob_hash>`

### 2. Purge Unreachable Secrets
Permanently remove the leaked secret residing in unreachable objects by expiring reflogs and forcing garbage collection:
```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```
*Note: You can also manually delete the loose object file from `.git/objects/<xx>/<yy...>` if its hash is known.*

### 3. Verify Eradication and History Preservation
Ensure the secret is no longer recoverable and legitimate history is intact:
- Run `git fsck --unreachable --no-reflogs` and `git cat-file -p <blob_hash>` to confirm the blob is gone.
- Search the `.git` directory for traces: `grep -r '<secret_pattern>' .git/`
- Inspect packfiles: `git verify-pack -v .git/objects/pack/*.idx`
- Dump all reachable objects to grep for the secret:
  ```bash
  git rev-list --objects --all | while read hash rest; do git cat-file -p "$hash" 2>/dev/null; done | grep '<secret_pattern>'
  ```
- Run `git log --oneline --all` to confirm legitimate history is preserved.
