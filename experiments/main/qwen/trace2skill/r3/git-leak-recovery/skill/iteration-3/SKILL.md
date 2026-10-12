---
name: git-leak-recovery
description: General starting point for solving tasks in the git-leak-recovery family.
---

# git-leak-recovery

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Workflow

### 1. Recover Unreachable Staged Blobs
When a file is staged but never committed and then removed from the index, its blob remains as a dangling object.
- Use `git fsck --dangling --no-reflogs` or `git fsck --unreachable` to identify the hash of the dangling blob.
- Extract its contents using `git cat-file -p <blob-hash>` to recover the secret or file.

### 2. Permanently Erase Leaked Secrets and Unreachable Objects
To ensure a leaked secret cannot be recovered from the Git object database:
- **Direct Deletion (Loose Objects)**: If the object is loose, locate it at `.git/objects/<first-2-chars>/<remaining-38-chars>` and delete it using `rm`. Do not rely solely on `git gc` as it may defer cleanup or pack the object.
- **Reflogs and Garbage Collection**: Expire all reflogs immediately (`git reflog expire --expire=now --all`) and run aggressive garbage collection (`git gc --prune=now`) to clean up any remaining unreachable objects or packfiles.

### 3. Verify Eradication and Repo Integrity
After cleanup, verify the secret is completely gone and the repository is intact:
- Search for the secret plaintext: `grep -r "secret_pattern" .git/ || echo "Clean"`
- Check packfiles and remaining objects: Use `git verify-pack -v .git/objects/pack/*.pack` or `find .git/objects -type f` and inspect with `git cat-file -p` to guarantee the secret string does not appear anywhere.
- Confirm legitimate state: Run `git log --oneline --all` and `git status` to ensure commits, branches, and working tree files are preserved.

