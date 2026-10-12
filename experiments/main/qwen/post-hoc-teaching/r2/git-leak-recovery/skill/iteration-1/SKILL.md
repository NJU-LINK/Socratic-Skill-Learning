---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository's object database or metadata,
  write it to /app/secret.txt, then purge all traces of the secret from the repo
  while preserving legitimate branches, files, tags, and commit messages.
  Covers secrets hidden as unreachable blobs, in stashes (live or dropped), in
  reflog entries from amended/reset commits, on deleted branches, in replace refs,
  in annotated tags, in reachable history, or in submodule object databases.
---

# Git Leak Recovery

## Overview

A secret (matching pattern `secret[...]`) was accidentally introduced into a Git
repository and must be (1) recovered and (2) completely purged. The secret may be
hidden in various locations within Git's storage model, and the cleanup must
eliminate every trace while preserving all legitimate repository content.

## Phase 1: Reconnaissance

Before attempting recovery, survey the repository to understand its structure and
locate where the secret resides.

```bash
cd /app/repo

# Basic structure
git log --all --oneline --graph --decorate
git branch -a
git tag -l
git stash list
git remote -v

# Check for replace refs
git for-each-ref refs/replace/

# Check for submodules
cat .gitmodules 2>/dev/null
ls .git/modules/ 2>/dev/null
```

## Phase 2: Recovery — Locate the Secret

The secret format is `secret[...]`. Search systematically through every possible
Git storage location. **Order matters**: start with the most common/likely
locations.

### 2a. Search all reachable objects (commits, trees, blobs)

```bash
# Search all blobs reachable from any ref
git rev-list --all --objects | while read hash rest; do
  content=$(git cat-file -p "$hash" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    echo "FOUND in $hash: $content"
  fi
done
```

### 2b. Search unreachable/dangling objects

This is the v01 scenario: a file was `git add`-ed then removed from the index,
leaving a dangling blob.

```bash
# Find all unreachable objects
git fsck --unreachable --no-reflogs --dangling 2>&1

# For each unreachable blob, check its content
git fsck --unreachable --no-reflogs 2>&1 | grep 'unreachable blob' | awk '{print $3}' | while read hash; do
  content=$(git cat-file -p "$hash" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    echo "FOUND dangling blob $hash: $content"
  fi
done
```

Also check with `--full` flag and without `--no-reflogs` to catch objects only
visible through reflogs:

```bash
git fsck --full --unreachable --dangling 2>&1 | grep 'unreachable blob' | awk '{print $3}' | while read hash; do
  content=$(git cat-file -p "$hash" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    echo "FOUND blob $hash: $content"
  fi
done
```

### 2c. Search reflogs for amended/reset-away commits

If a commit containing the secret was amended or reset away, it lives in the reflog.

```bash
# Check reflog for all refs
git reflog --all

# For each reflog entry, inspect the commit's tree
git reflog --all --format='%H %gd' | while read hash gd; do
  # Check all blobs in this commit's tree
  git ls-tree -r "$hash" 2>/dev/null | awk '{print $3}' | while read blob; do
    content=$(git cat-file -p "$blob" 2>/dev/null)
    if echo "$content" | grep -q 'secret\['; then
      echo "FOUND in reflog $gd ($hash), blob $blob: $content"
    fi
  done
done
```

### 2d. Search stash (including dropped stash reflog)

```bash
# Live stashes
git stash list
git stash show -p  # for each stash

# Dropped stash (check refs/stash reflog)
git reflog show refs/stash 2>/dev/null
# Then inspect each entry as in 2c
```

### 2e. Search deleted branches

```bash
# Check reflog for branch references that no longer exist
git reflog | grep 'branch:' | grep -v 'refs/heads/'
# Or look for entries referencing deleted branches
git for-each-ref --format='%(refname)' refs/ | while read ref; do
  git reflog show "$ref" 2>/dev/null
done
```

### 2f. Search annotated tags

```bash
git tag -l | while read tag; do
  # Tag object itself
  git cat-file -p "$(git rev-parse "$tag")" 2>/dev/null | grep 'secret\['
  # Tagged object (commit/tree/blob)
  git cat-file -p "$tag^{commit}" 2>/dev/null
  git ls-tree -r "$tag^{commit}" 2>/dev/null | awk '{print $3}' | while read blob; do
    git cat-file -p "$blob" 2>/dev/null | grep 'secret\['
  done
done
```

### 2g. Search replace refs

```bash
git for-each-ref refs/replace/ | while read obj type ref; do
  git cat-file -p "$obj" 2>/dev/null | grep 'secret\['
done
```

### 2h. Search submodule object databases

```bash
if [ -d .git/modules ]; then
  for mod in .git/modules/*/; do
    GIT_DIR="$mod" git fsck --unreachable 2>&1 | grep 'blob' | awk '{print $3}' | while read hash; do
      GIT_DIR="$mod" git cat-file -p "$hash" 2>/dev/null | grep 'secret\['
    done
  done
fi
```

### 2i. Brute-force search of all pack files and loose objects

If the above targeted searches fail, enumerate every object in the repo:

```bash
# All loose objects
find .git/objects -type f | sed 's|.git/objects/||;s|/||' | while read hash; do
  type=$(git cat-file -t "$hash" 2>/dev/null)
  if [ "$type" = "blob" ]; then
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && echo "FOUND: $hash"
  fi
done

# All objects in packs
git verify-pack -v .git/objects/pack/*.idx 2>/dev/null | grep ' blob ' | awk '{print $1}' | while read hash; do
  git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && echo "FOUND: $hash"
done
```

### 2j. Write the recovered secret

```bash
echo "secret[RECOVERED_VALUE]" > /app/secret.txt
```

## Phase 3: Cleanup — Purge All Traces

After recovery, eliminate every copy of the secret from the repository. The
cleanup strategy depends on where the secret was found.

### 3a. Unreachable/dangling blobs (v01 scenario)

Expire all reflogs and garbage-collect:

```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### 3b. Stash entries

```bash
git stash drop stash@{N}  # for each stash containing the secret
# Then expire reflogs and gc
git reflog expire --expire=now --all
git gc --prune=now
```

### 3c. Replace refs

```bash
git for-each-ref --format='%(refname)' refs/replace/ | while read ref; do
  git update-ref -d "$ref"
done
```

### 3d. Annotated tags containing the secret

```bash
git tag -d <tagname>
```

### 3e. Secret in reachable history (committed secret)

This requires history rewriting. `git filter-repo` is preferred but is an
external Python package (`pip install git-filter-repo`) and may not be
installed. Always check for it and fall back to `git filter-branch` if needed.

#### Option A: `git filter-repo` (preferred, if installed)

```bash
if command -v git-filter-repo &>/dev/null; then
  # Remove a specific file from all history:
  git filter-repo --invert-paths --path <secret-file> --force

  # Or scrub secret content from all blobs:
  git filter-repo --blob-callback '
    if b"secret[" in blob.data:
      blob.data = b""  # or remove the specific line
  ' --force
fi
```

After `filter-repo`, clean up its metadata directory:
```bash
rm -rf .git/filter-repo/
```

#### Option B: `git filter-branch` fallback (always available in core git)

```bash
# Remove a specific file from all history:
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch <secret-file>" \
  --prune-empty -- --all
```

**CRITICAL**: `git filter-branch` creates backup refs under `refs/original/`
that still point to the OLD (pre-rewrite) commits containing the secret.
These refs make the old commits reachable, so `git gc` will NOT prune them.
The secret survives cleanup unless you delete these backup refs.

```bash
# IMMEDIATELY after filter-branch, delete all backup refs:
git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null | while read ref; do
  git update-ref -d "$ref"
done
```

This ordering is non-negotiable: as long as `refs/original/` refs exist, the
old commits are reachable and gc will keep them.

#### After either option, finalize cleanup:
```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### 3f. Secret in deleted branch reflog entries

```bash
# Remove the reflog entries
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

### 3g. Submodule objects

```bash
cd .git/modules/<submodule>
git reflog expire --expire=now --all
git gc --prune=now --aggressive
cd /app/repo
```

### 3h. Universal cleanup (always do this as final step)

Regardless of the secret's location, always perform these final steps to ensure
no traces remain. **Ordering matters**: refs must be deleted BEFORE gc, because
gc only prunes objects that are unreachable from any ref.

```bash
# 1. Expire ALL reflogs (this is critical — reflogs can keep objects alive)
git reflog expire --expire=now --all

# 2. Remove any replace refs
git for-each-ref --format='%(refname)' refs/replace/ 2>/dev/null | while read ref; do
  git update-ref -d "$ref"
done

# 3. Remove backup refs from filter-branch (refs/original/)
#    These point to OLD commits that contain the secret.
#    As long as they exist, gc treats those commits as reachable.
#    filter-repo does NOT create these by default, but filter-branch does,
#    and some older filter-repo versions or manual filter-branch usage will too.
git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null | while read ref; do
  git update-ref -d "$ref"
done

# 4. Aggressive garbage collection to prune all unreachable objects
#    This MUST come after steps 2 and 3, which remove the refs that
#    would otherwise keep tainted objects reachable.
git gc --prune=now --aggressive

# 5. Remove any leftover lost-found
rm -rf .git/lost-found
```

## Phase 4: Verification

After cleanup, verify that:
1. The secret is no longer findable anywhere in the repo
2. All legitimate content is preserved

```bash
# Verify secret is gone from all objects.
# IMPORTANT: We use a sentinel file instead of a shell variable because
# piped while-read loops run in subshells in bash, and variable assignments
# inside them do NOT propagate back to the parent shell.
rm -f /tmp/secret_still_found

# Check all loose objects
for objpath in $(find .git/objects -type f 2>/dev/null | sed 's|.git/objects/||;s|/||'); do
  git cat-file -p "$objpath" 2>/dev/null | grep -q 'secret\[' && \
    echo "STILL FOUND in loose object $objpath" && touch /tmp/secret_still_found
done

# Check all packed objects
if ls .git/objects/pack/*.idx &>/dev/null; then
  for hash in $(git verify-pack -v .git/objects/pack/*.idx 2>/dev/null | grep ' blob ' | awk '{print $1}'); do
    git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && \
      echo "STILL FOUND in packed object $hash" && touch /tmp/secret_still_found
  done
fi

# Check unreachable objects (catches anything fsck finds that wasn't in the above)
for hash in $(git fsck --unreachable --no-reflogs 2>&1 | grep 'blob' | awk '{print $3}'); do
  git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\[' && \
    echo "STILL FOUND in unreachable blob $hash" && touch /tmp/secret_still_found
done

# Final verdict
if [ -f /tmp/secret_still_found ]; then
  echo "CLEANUP FAILED: secret still exists in repository objects"
  rm -f /tmp/secret_still_found
  exit 1
else
  echo "CLEANUP VERIFIED: secret not found in any repository object"
fi

# Verify legitimate content preserved
git log --all --oneline --graph --decorate
git branch -a
git tag -l
```

## Decision Flowchart

```
START
  │
  ├─ Survey repo structure (branches, tags, stash, reflogs, replace refs, submodules)
  │
  ├─ Search reachable objects (2a)
  │   └─ Found? → Record location → Go to appropriate cleanup
  │
  ├─ Search unreachable/dangling objects (2b)
  │   └─ Found? → It's a dangling blob → Cleanup 3a + 3h
  │
  ├─ Search reflogs (2c)
  │   └─ Found? → Amended/reset commit → Cleanup 3f + 3h
  │
  ├─ Search stash (2d)
  │   └─ Found? → Cleanup 3b + 3h
  │
  ├─ Search tags (2f), replace refs (2g), submodules (2h)
  │   └─ Found? → Cleanup accordingly + 3h
  │
  ├─ Brute-force all objects (2i)
  │   └─ Found? → Determine location type → Cleanup accordingly + 3h
  │
  └─ Write secret to /app/secret.txt → Verify cleanup
```

## Key Principles

1. **Recovery before cleanup**: Always recover and save the secret before any
   destructive operations.
2. **Reflogs are the enemy of cleanup**: Git reflogs keep "deleted" objects alive.
   Always expire reflogs before gc.
3. **`--prune=now` is essential**: Default gc may keep objects for 2 weeks.
   Always use `--prune=now`.
4. **`--aggressive` for thoroughness**: Ensures all packs are repacked and
   unreachable objects are fully removed.
5. **Delete backup refs BEFORE gc**: `git filter-branch` stores original refs
   under `refs/original/` that still point to old commits containing the secret.
   As long as these refs exist, gc treats those commits as reachable and will
   NOT prune them. Always delete `refs/original/` before running gc.
6. **Preserve legitimate content**: Never delete branches, tags, or commits that
   don't contain the secret. When rewriting history, only remove the tainted
   content.
7. **Verify after cleanup**: Always confirm the secret is truly gone by searching
   all object types including unreachable ones. Use sentinel files or process
   substitution instead of piped while-loops to avoid bash subshell
   variable-scope bugs.
8. **Multiple locations possible**: The secret might exist in more than one place
   (e.g., committed AND in a stash). Search exhaustively.
