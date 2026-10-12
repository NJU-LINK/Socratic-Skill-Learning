---
name: git-leak-recovery
description: Recover secrets leaked into Git repositories and clean them from all storage locations (reachable history, unreachable objects, stashes, refs, tags) while preserving legitimate content.
---

# Git Leak Recovery

## Overview

This skill handles the recovery and cleanup of secrets accidentally committed or staged in Git repositories. The secret format is typically `secret[...]`. The procedure must handle secrets in various locations and preserve legitimate repository content.

**Paths**: The repo path and output path come from the task instruction (typically `/app/repo` and `/app/secret.txt`). Substitute accordingly.

## Critical Principle

**Always RECOVER before CLEANUP.** You cannot clean what you haven't found, and you cannot verify without a thorough search. The four phases must execute in strict order.

**Variations must be discovered upfront.** Every spec-declared variation (submodules, stashes, replace refs, tags, etc.) needs a decision point in the main procedure, not an afterthought. Phase 0 discovers all variations; Phases 1-3 run for each discovered location.

## Phase 0: DISCOVER REPO STRUCTURE

Before searching for secrets, discover the repository structure and all variations that might contain secrets. This phase runs once and determines the scope of Phases 1-3.

```bash
# 0.1 Check for submodules
git submodule status

# 0.2 Check for nested repos (non-submodule .git directories)
# Use -mindepth 2 to exclude the main repo's .git directory (which is at depth 1)
find . -mindepth 2 -name ".git" -type d 2>/dev/null

# 0.3 Check repo complexity
git branch -a  # How many branches?
git tag -l     # Any tags?
git log --all --oneline | wc -l  # How many commits?

# 0.4 Check for stashes
git stash list

# 0.5 Check for replace refs
git for-each-ref refs/replace/

# 0.6 Check for backup refs (from filter-branch)
git for-each-ref refs/original/

# 0.7 List all refs for awareness
git for-each-ref --format='%(refname) %(objectname)'
```

**Decision**: Based on Phase 0 output, determine:
- How many repos/submodules need processing? (main repo + each submodule)
- Which cleanup methods will be needed? (stash drop, tag delete, ref deletion, history rewrite, etc.)
- What is the repo complexity? (single branch, multiple branches, tags, merges)

For each discovered repo/submodule, run Phases 1-3.

## Phase 1: RECOVER — Search Everywhere

Before touching anything, search all possible locations where the secret might exist. **Run this phase for each repo/submodule discovered in Phase 0.**

### 1.1 Search Reachable History (Primary Method)

The secret may be in a commit still pointed to by a branch. Use pickaxe search first:

```bash
# PRIMARY: Use pickaxe search (-S) — fast, safe for any repo size
git log --all -S 'secret\[' -p

# If the above finds commits, extract the exact secret value from the patch output
```

**Fallback** (if pickaxe finds nothing but you suspect reachable history):
```bash
# Brute-force grep across all reachable trees
git rev-list --all | while read commit; do
  git grep 'secret\[' "$commit" 2>/dev/null
done
```

### 1.2 Search Unreachable Objects

The secret may be in a blob, commit, or tree that no reference points to (e.g., staged then removed, amended away, reset):

```bash
# Find all unreachable objects
git fsck --unreachable --no-reflogs 2>&1

# Search each unreachable object
for obj in $(git fsck --unreachable --no-reflogs 2>&1 | awk '{print $3}'); do
  git cat-file -p "$obj" 2>/dev/null | grep 'secret\[' && echo "FOUND in $obj"
done
```

### 1.3 Search Discovered Locations

For each location discovered in Phase 0, search for the secret:

```bash
# If stashes were found in Phase 0:
for stash in $(git stash list --format='%H'); do
  git stash show -p "$stash" 2>/dev/null | grep 'secret\[' && echo "FOUND in stash $stash"
done

# If replace refs were found in Phase 0:
for ref in $(git for-each-ref --format='%(objectname)' refs/replace/); do
  git cat-file -p "$ref" 2>/dev/null | grep 'secret\[' && echo "FOUND in replace ref $ref"
done

# If backup refs were found in Phase 0:
for ref in $(git for-each-ref --format='%(objectname)' refs/original/); do
  git cat-file -p "$ref" 2>/dev/null | grep 'secret\[' && echo "FOUND in backup ref $ref"
done

# If tags were found in Phase 0:
for tag in $(git tag -l); do
  git cat-file -p "$tag" 2>/dev/null | grep 'secret\[' && echo "FOUND in tag $tag"
done
```

**Note**: Only run the checks for locations that actually exist (as discovered in Phase 0).

### 1.4 Brute Force Search (All Objects)

If the secret isn't found above, search every object in the repository:

```bash
# Search all reachable objects
git rev-list --all --objects | cut -d' ' -f1 | while read h; do
  git cat-file -p "$h" 2>/dev/null | grep 'secret\[' && echo "REACHABLE: $h"
done

# Search loose objects
find .git/objects -type f ! -path "*/pack/*" ! -path "*/info/*" | while read f; do
  h=$(echo "$f" | sed 's|.*/objects/\(..\)/\(.*\)|\1\2|')
  git cat-file -p "$h" 2>/dev/null | grep 'secret\[' && echo "LOOSE: $h"
done
```

### 1.5 Record the Secret

Once found, extract and save it:
```bash
echo 'secret[...]' > /app/secret.txt
```

## Phase 2: CLEANUP — Targeted by Location

The cleanup method must match where the secret is located. Different locations require different approaches. **Run this phase for each repo/submodule where a secret was found in Phase 1.**

### 2.1 Secret in Unreachable Objects

If the secret is only in unreachable objects (blobs, commits, trees):

```bash
# Expire all reflogs immediately
git reflog expire --expire=now --all

# Aggressively garbage collect
git gc --prune=now --aggressive
```

### 2.2 Secret in Reachable History

If the secret is in a commit still reachable from a branch:

**Option A: git filter-branch (always available, primary method)**
```bash
# Remove file from all history
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <path-to-secret-file>' \
  --prune-empty --tag-name-filter cat -- --all

# Clean up backup refs created by filter-branch
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

**Option B: git filter-repo (preferred if installed, faster)**
```bash
# Check availability
which git-filter-repo 2>/dev/null || pip install git-filter-repo

# Remove the file containing the secret from all history
git filter-repo --invert-paths --path <path-to-secret-file> --force

# If the secret is in a specific commit, rewrite that commit
git filter-repo --message-callback '
if "secret[" in message:
    message = message.replace("secret[...]", "[REDACTED]")
return message
' --force
```

### 2.3 Secret in Stash

If the secret is in a live stash:

```bash
# Drop the stash containing the secret
git stash drop <stash-number>

# Then gc to remove unreachable objects
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### 2.4 Secret in Replace Refs

If the secret is in a replace ref:

```bash
# Delete the replace ref
git update-ref -d refs/replace/<sha>

# Then gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### 2.5 Secret in Backup Refs

If the secret is in backup refs (from filter-branch):

```bash
# Delete all backup refs
git for-each-ref --format="%(refname)" refs/original/ | while read ref; do
  git update-ref -d "$ref"
done

# Then gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### 2.6 Secret in Tags

If the secret is in an annotated tag:

```bash
# Delete the tag
git tag -d <tag-name>

# Then gc
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### 2.7 Secret in Deleted Branch

If the secret is in a deleted branch (now unreachable):

```bash
# The branch deletion already made it unreachable
# Just gc to remove the objects
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

## Phase 3: VERIFY — Comprehensive Sweep

After cleanup, verify the secret is completely gone using multiple methods. **Run this phase for each repo/submodule that was cleaned in Phase 2.**

### 3.1 Verify Reachable Objects

```bash
# Search all reachable objects
git rev-list --all --objects | cut -d' ' -f1 | while read h; do
  git cat-file -p "$h" 2>/dev/null | grep 'secret\[' && echo "STILL PRESENT in $h"
done
```

If this finds the secret, cleanup was incomplete.

### 3.2 Verify No Unreachable Objects

```bash
# Check for unreachable objects (use --no-reflogs to ensure reflogs don't hide the secret)
git fsck --unreachable --no-reflogs 2>&1

# Should return nothing
```

### 3.3 Verify No Loose Objects

```bash
# Check for loose objects
find .git/objects -type f ! -path "*/pack/*" ! -path "*/info/*"

# NOTE: After gc --aggressive, objects are packed into .git/objects/pack/*.pack.
# Absence of loose objects does NOT mean the secret is gone — it may be in pack files.
# Always continue to Section 3.4 to verify pack contents.
```

### 3.4 Verify All Objects (Reachable + Unreachable, Loose + Packed)

This is the definitive verification step. It searches every object the repository knows about.

**Preferred method (Git 2.19+):**
```bash
# Single-pass: dump all object contents and grep once
# Note: --batch-all-objects is a modifier that requires --batch to output content
git cat-file --batch-all-objects --batch 2>/dev/null | grep 'secret\['
# If this returns nothing, the secret is completely gone.
```

**Fallback (older Git):**
```bash
# Enumerate all objects and check each one
git cat-file --batch-all-objects --batch-check='%(objectname)' 2>/dev/null | while read h; do
  git cat-file -p "$h" 2>/dev/null | grep 'secret\[' && echo "FOUND: $h"
done

# If --batch-all-objects is unavailable, use verify-pack for packed objects:
git verify-pack -v .git/objects/pack/*.idx 2>/dev/null | while read line; do
  h=$(echo "$line" | awk '{print $1}')
  [ -n "$h" ] && git cat-file -p "$h" 2>/dev/null | grep 'secret\[' && echo "IN PACK: $h"
done
```

### 3.5 Verify All Refs

```bash
# List all refs and ensure none point to tainted objects
git for-each-ref --format='%(refname) %(objectname)'

# Check stash
git stash list

# Check tags
git tag -l
```

### 3.6 Final Integrity Check

```bash
# Ensure repository is still functional
git status
git log --oneline --all

# Verify legitimate content is preserved
# (Check that expected files, branches, tags, and commit messages remain)
```

## Decision Tree

```
Found secret in:
├─ Unreachable object → gc --prune=now --aggressive
├─ Reachable history → filter-repo or filter-branch + gc
├─ Stash → stash drop + gc
├─ Replace ref → update-ref -d + gc
├─ Backup ref → delete refs/original/* + gc
├─ Tag → tag -d + gc
└─ Deleted branch → gc (already unreachable)
```

## Common Pitfalls

1. **Cleaning before recovering**: Always search and save the secret first
2. **Using only git fsck**: It only finds unreachable objects; secrets in reachable history need different methods
3. **Forgetting reflogs**: Reflogs can keep objects alive; expire them before gc
4. **Not verifying comprehensively**: Check reachable objects, unreachable objects, loose objects, and pack files
5. **Destroying legitimate content**: When using filter-repo/filter-branch, ensure you preserve legitimate files and commit messages

## Variation Handling

This skill handles the following variations:

- **secret_location**: Secret may be in unreachable blobs, reachable commits, stashes, replace refs, backup refs, tags, or deleted branches
- **repo_complexity**: Repository may have multiple branches, tags, merges, or complex history
- **cleanup_scope**: Cleanup may require dropping stashes, removing refs, rewriting history, or pruning objects

The procedure adapts by:
1. **Phase 0**: Discovering all variations (submodules, stashes, refs, tags, etc.)
2. **Phase 1**: Searching all possible locations in each discovered repo
3. **Phase 2**: Selecting the appropriate cleanup method based on where the secret was found
4. **Phase 3**: Verifying comprehensively in each cleaned repo

All variations are handled through the discover-then-process pattern: Phase 0 discovers what exists, Phases 1-3 process each discovered location.
