---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository (where it may reside in dangling
  blobs, packed objects, stashes, reflogs, replace/backup refs, annotated tags,
  reachable history, deleted branches, or submodule object databases), write it
  to an output file, then scrub every copy from the repository while preserving
  all legitimate branches, files, tags, and commit messages.
---

# Git Leak Recovery

## Overview

A secret (matching a known pattern, e.g. `secret[...]`) was introduced into a Git
repository and must be (1) recovered and (2) completely removed. The secret may
live in any of several Git storage locations. The cleanup must not damage
legitimate repository content.

**Critical invariant: ALWAYS recover the secret BEFORE any destructive cleanup.**

## Phase 1 — Reconnaissance

Before touching anything, understand the repository:

```bash
cd "$REPO"
git log --all --oneline --graph          # commit topology
git branch -a                             # all branches
git tag -l                                # all tags
git stash list                            # live stashes
git for-each-ref                          # every ref
git fsck --unreachable --no-reflogs       # unreachable objects
```

Identify the secret pattern from the task (e.g. `secret[...]`).

## Phase 2 — Recovery

### Step 1: Comprehensive Sweep (MANDATORY — run this FIRST)

Search **every object** in the database to find the secret. This is the definitive
recovery method — it catches all hiding places in one atomic operation.

**Run this single command that searches loose objects, packed objects, and submodules:**

```bash
# Search all loose objects
find .git/objects -type f | grep -v pack | grep -v info | sed 's|.git/objects/||;s|/||' | while read h; do
  content=$(git cat-file -p "$h" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    echo "FOUND in loose $h ($(git cat-file -t $h)): $(echo "$content" | grep -o 'secret\[[^]]*\]')"
  fi
done

# Search all packed objects
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] || continue
  git verify-pack -v "$idx" 2>/dev/null | awk '{print $1}' | while read h; do
    content=$(git cat-file -p "$h" 2>/dev/null)
    if echo "$content" | grep -q 'secret\['; then
      echo "FOUND in packed $h ($(git cat-file -t $h)): $(echo "$content" | grep -o 'secret\[[^]]*\]')"
    fi
  done
done

# Search submodule object databases (both loose and packed)
for mod_gitdir in .git/modules/*/; do
  [ -d "$mod_gitdir" ] || continue
  find "$mod_gitdir/objects" -type f | grep -v pack | grep -v info | \
    sed "s|${mod_gitdir}objects/||;s|/||" | while read h; do
    content=$(git --git-dir="$mod_gitdir" cat-file -p "$h" 2>/dev/null)
    if echo "$content" | grep -q 'secret\['; then
      echo "FOUND in submodule loose $h: $(echo "$content" | grep -o 'secret\[[^]]*\]')"
    fi
  done
  for idx in "$mod_gitdir/objects/pack/"*.idx; do
    [ -f "$idx" ] || continue
    git --git-dir="$mod_gitdir" verify-pack -v "$idx" 2>/dev/null | awk '{print $1}' | while read h; do
      content=$(git --git-dir="$mod_gitdir" cat-file -p "$h" 2>/dev/null)
      if echo "$content" | grep -q 'secret\['; then
        echo "FOUND in submodule packed $h: $(echo "$content" | grep -o 'secret\[[^]]*\]')"
      fi
    done
  done
done
```

**IMPORTANT**: Run ALL THREE sections (loose, packed, submodules) even if you find the secret early.
The secret may exist in multiple locations, and you need to know about all of them for cleanup.

**Record WHERE the secret was found** (loose blob, packed commit, submodule, etc.) — this
determines the cleanup strategy in Phase 3.

### Step 2: Write the Secret

Once found, write it immediately:

```bash
echo -n 'secret[THE_VALUE]' > /app/secret.txt
```

## Phase 3 — Cleanup

Clean each hiding place that contained the secret. Order matters: remove refs
first, then expire reflogs, then garbage-collect.

### 3a. Remove tainted refs

```bash
# Stashes
git stash drop stash@{N}   # for each tainted stash

# Replace/backup refs
git for-each-ref --format='%(refname)' refs/replace/ refs/original/ refs/backups/ | while read ref; do
  git update-ref -d "$ref"
done

# Tainted tags (only if the tag object itself contains the secret)
git for-each-ref refs/tags/ --format='%(objectname) %(objecttype) %(refname)' | \
while read obj type ref; do
  if [ "$type" = "tag" ]; then
    if git cat-file -p "$obj" 2>/dev/null | grep -q 'secret\['; then
      git tag -d "${ref#refs/tags/}"
    fi
  fi
done

# Tainted branches
# (only delete if the branch itself was created to hold the secret; preserve legitimate branches)
```

### 3b. Rewrite reachable history if secret is in committed content

If the secret was found in any reachable object (detected during Phase 2),
rewrite history to remove it. The approach depends on whether the secret
occupies its own file or is embedded inside a legitimate file's content.

#### File-level removal (secret is in its own file)

```bash
# Prefer git-filter-repo if available:
git filter-repo --path PATH_TO_SECRET_FILE --invert-paths --force

# Or with filter-branch:
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch PATH_TO_SECRET_FILE' \
  --prune-empty -- --all
```

#### Content-level replacement (secret embedded inside a legitimate file)

```bash
# Using git filter-repo (preferred — faster, safer):
echo "secret[THE_VALUE]==>REDACTED" > /tmp/expressions.txt
git filter-repo --replace-text /tmp/expressions.txt --force

# Using filter-branch with tree-filter (slower but works without filter-repo):
git filter-branch --force --tree-filter \
  'find . -type f -exec sed -i "s/secret\[THE_VALUE\]/REDACTED/g" {} +' \
  -- --all
```

**After rewriting with filter-branch, remove the backup refs it creates:**

```bash
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do
  git update-ref -d "$ref"
done
```

(Note: `git filter-repo` handles this automatically and does not create
`refs/original/`.)

### 3c. Expire all reflogs

```bash
git reflog expire --expire=now --all
```

### 3d. Garbage-collect everything

```bash
git gc --prune=now
```

This repacks reachable objects and prunes ALL unreachable objects — both loose
and packed. This is more thorough than `git prune --expire=now` alone, which
only handles loose objects.

### 3e. Submodule cleanup

If submodules contain the secret, repeat the cleanup inside each submodule's
git dir.

## Phase 4 — Verification

### 4a. No unreachable objects remain

```bash
git fsck --unreachable --no-reflogs 2>&1
# Should produce zero output (or only "notice" lines, no object hashes)
```

### 4b. No objects contain the secret

Run the same comprehensive sweep from Phase 2 Step 1 (all three sections:
loose, packed, and submodules). Should produce zero output across all sections.

```bash
# Loose objects
find .git/objects -type f | grep -v pack | grep -v info | sed 's|.git/objects/||;s|/||' | while read h; do
  git cat-file -p "$h" 2>/dev/null
done | grep 'secret\['

# Packed objects
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] || continue
  git verify-pack -v "$idx" 2>/dev/null | awk '{print $1}' | while read h; do
    git cat-file -p "$h" 2>/dev/null
  done | grep 'secret\['
done

# Submodule objects (loose + packed)
for mod_gitdir in .git/modules/*/; do
  [ -d "$mod_gitdir" ] || continue
  find "$mod_gitdir/objects" -type f | grep -v pack | grep -v info | \
    sed "s|${mod_gitdir}objects/||;s|/||" | while read h; do
    git --git-dir="$mod_gitdir" cat-file -p "$h" 2>/dev/null
  done | grep 'secret\['
  for idx in "$mod_gitdir/objects/pack/"*.idx; do
    [ -f "$idx" ] || continue
    git --git-dir="$mod_gitdir" verify-pack -v "$idx" 2>/dev/null | awk '{print $1}' | while read h; do
      git --git-dir="$mod_gitdir" cat-file -p "$h" 2>/dev/null
    done | grep 'secret\['
  done
done
```

### 4c. Legitimate content is preserved

```bash
git log --all --oneline --graph   # all legitimate commits present
git branch -a                      # all legitimate branches present
git tag -l                         # all legitimate tags present
# Spot-check key files still have correct content
```

## Key Principles

1. **Recover before cleanup.** Once you prune/gc, unreachable objects are gone forever.
2. **Comprehensive sweep is the primary recovery method.** It searches every object and catches all hiding places. Run it FIRST.
3. **Complete the full sweep even after finding the secret.** The secret may exist in multiple locations (e.g., both loose and packed objects). Run all three sections (loose, packed, submodules) to ensure complete coverage.
4. **`git gc --prune=now` > `git prune`.** The former handles packed objects too.
5. **Reflogs keep objects alive.** Always expire reflogs before final gc.
6. **`filter-branch` creates `refs/original/`.** Always delete these after rewriting.
7. **Packed unreachable objects survive `git prune`.** Only `git gc --prune=now` removes them.
8. **Preserve legitimate content.** Every branch, tag, commit message, and non-secret file must remain intact.

## Decision Flowchart

```
START
  |
  v
Reconnaissance: understand repo topology, refs, stashes
  |
  v
COMPREHENSIVE SWEEP: search every object (loose + packed + submodules)
  - Records WHERE secret was found (informs cleanup strategy)
  - Guarantees nothing is missed
  |
  v
Write secret to output file
  |
  v
Cleanup (based on where secret was found):
  - Remove tainted refs (stashes, replace refs, tainted tags)
  - Rewrite history if secret is in reachable commits
  - Expire all reflogs
  - git gc --prune=now
  |
  v
Verify:
  - git fsck shows no unreachable objects
  - Comprehensive sweep finds zero matches
  - Legitimate content intact
```
