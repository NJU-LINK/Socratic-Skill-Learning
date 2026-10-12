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

The secret format is `secret[...]`. The most robust approach is a **unified
scan** that checks ALL objects in the repository in a single pass, regardless
of where the secret is hidden. This covers blobs (file content), commits
(commit messages), tags (tag annotations), and unreachable/dangling objects.

### 2.0a. Quick check: working tree and index

Before scanning git objects, check if the secret is still in a file:

```bash
# Check working tree (tracked and untracked files)
if grep -rq 'secret\[' . --exclude-dir=.git 2>/dev/null; then
  echo "FOUND in working tree:"
  grep -r 'secret\[' . --exclude-dir=.git 2>/dev/null
fi

# Check index (staged files)
if git diff --cached --diff-filter=A --name-only 2>/dev/null | xargs -r git show : 2>/dev/null | grep -q 'secret\['; then
  echo "FOUND in index (staged but not committed)"
  git diff --cached --diff-filter=A --name-only 2>/dev/null | xargs -r git show : 2>/dev/null | grep 'secret\['
fi
```

If found here, extract the secret value and proceed to cleanup.

### 2.0b. Unified scan (PRIMARY — run this first)

This single command finds the secret in any object type, reachable or not:

```bash
# Unified scan: find the secret in ANY object in the repo
# Covers: reachable blobs, unreachable blobs, commit messages, tag annotations,
# reflog-only commits, and any other object in the repository.
{
  # All objects reachable from any ref (branches, tags, etc.)
  git rev-list --all --objects 2>/dev/null | awk '{print $1}'
  # All objects NOT reachable from any ref (dangling blobs, orphaned commits,
  # reflog-only objects, etc.)
  git fsck --unreachable --no-reflogs 2>&1 | awk '/unreachable/{print $3}'
} | sort -u | while read hash; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "FOUND in $(git cat-file -t "$hash" 2>/dev/null) $hash"
  fi
done
```

**Why this works**: `git rev-list --all --objects` enumerates every object
reachable from any ref. `git fsck --unreachable --no-reflogs` enumerates every
object NOT reachable from any ref. The union of these two sets is ALL objects
in the repository. For each object, `git cat-file -p` prints its content:
- For **blobs**: the file content
- For **commits**: the commit message (along with metadata)
- For **tags**: the tag annotation message
- For **trees**: directory entries (unlikely to contain the pattern)

If the secret is in ANY of these, the grep will find it.

**After finding the secret**, note the object type and hash:
- If it's a **blob**: the secret was in a file (staged, committed, stashed, etc.)
- If it's a **commit**: the secret was in a commit message
- If it's a **tag**: the secret was in a tag annotation
- If the object is **unreachable**: it was orphaned (staged-then-removed, amended away, etc.)

Write the recovered secret value to `/app/secret.txt`:
```bash
echo "secret[RECOVERED_VALUE]" > /app/secret.txt
```

### 2.0c. Discover the filename for a reachable blob (if needed for cleanup)

If the unified scan found a **reachable blob** (the secret is in committed file
content), you need to know which file it corresponds to for cleanup with
`--invert-paths --path <filename>`. The unified scan gives you the blob hash
but not the filename.

```bash
# Given a blob hash from the unified scan, find which file(s) it corresponds to:
git log --all --find-object=<BLOB_HASH> --name-only --pretty=format:"%H %s"
```

This shows all commits that reference this exact blob and the filenames they
used. The filename is what you pass to `--invert-paths --path <filename>` in
Phase 3e.

**Note**: If the blob is **unreachable** (orphaned), `--find-object` returns
nothing — that's expected. Unreachable blobs aren't in any commit's tree, so
there's no filename to discover. Cleanup is just reflog expire + gc (Phase 3a).

If the blob appears under multiple filenames across history (e.g., renamed),
you need to remove ALL of them:
```bash
# Get all filenames that ever contained this blob
git log --all --find-object=<BLOB_HASH> --name-only --pretty=format:"" | sort -u | grep -v '^$'
# Then use --invert-paths for each, or use --blob-callback instead
```

### 2.1. Submodule object databases (separate from main repo)

The unified scan (2.0b) covers the main repository's object database. However,
if the repository contains submodules (indicated by `.git/modules/`), each
submodule has its own separate object database that the main scan doesn't reach.

If `.git/modules/` exists, run the unified scan pattern against each submodule:

```bash
if [ -d .git/modules ]; then
  for mod in .git/modules/*/; do
    [ -d "$mod" ] || continue
    echo "Scanning submodule: $mod"
    {
      GIT_DIR="$mod" git rev-list --all --objects 2>/dev/null | awk '{print $1}'
      GIT_DIR="$mod" git fsck --unreachable --no-reflogs 2>&1 | awk '/unreachable/{print $3}'
    } | sort -u | while read hash; do
      if GIT_DIR="$mod" git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        echo "FOUND in submodule $mod: $(GIT_DIR="$mod" git cat-file -t "$hash" 2>/dev/null) $hash"
        GIT_DIR="$mod" git cat-file -p "$hash" 2>/dev/null | grep 'secret\['
      fi
    done
  done
fi
```

This uses the same unified scan pattern as 2.0b but with `GIT_DIR` set to each
submodule's `.git` directory, ensuring all object types (blobs, commits, tags)
are checked in each submodule's database.

If the secret is found in a submodule, cleanup requires running the appropriate
cleanup steps (Phase 3) within that submodule's context, also with `GIT_DIR` set.

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

If the unified scan reports `FOUND in tag <hash>`, the secret is in the tag
annotation message. Delete the tag:

```bash
git tag -d <tagname>
```

Note: lightweight tags have no separate tag object — they point directly to a
commit. If the secret is in a commit that a lightweight tag points to, use 3e
(history rewriting) instead.

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

  # If the secret is in a COMMIT MESSAGE (not file content):
  git filter-repo --message-callback '
    if b"secret[" in message:
      import re
      message = re.sub(b"secret\\[[^\\]]*\\]", b"[REDACTED]", message)
    return message
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

# If the secret is in a COMMIT MESSAGE (not file content):
git filter-branch --force --msg-filter '
  sed "s/secret\[[^]]*\]/[REDACTED]/g"
' -- --all
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

**Use the unified scan from Phase 2 as your verification.** This single scan checks ALL object types (blobs, commits, tags) whether reachable or unreachable, packed or loose. It's the same command you used to find the secret, now confirming it's gone.

```bash
# Phase 4: Post-cleanup verification — re-run unified scan
# If this finds ANY match, cleanup was incomplete.
rm -f /tmp/secret_still_found

{
  # All objects reachable from any ref (branches, tags, etc.)
  git rev-list --all --objects 2>/dev/null | awk '{print $1}'
  # All objects NOT reachable from any ref (dangling blobs, orphaned commits, etc.)
  git fsck --unreachable --no-reflogs 2>&1 | awk '/unreachable/{print $3}'
} | sort -u | while read hash; do
  if git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
    echo "STILL FOUND in $(git cat-file -t "$hash" 2>/dev/null) $hash"
    touch /tmp/secret_still_found
  fi
done

# Also check submodule object databases (if any)
if [ -d .git/modules ]; then
  for mod in .git/modules/*/; do
    [ -d "$mod" ] || continue
    for hash in $(GIT_DIR="$mod" git rev-list --all --objects 2>/dev/null | awk '{print $1}'; \
                  GIT_DIR="$mod" git fsck --unreachable --no-reflogs 2>&1 | awk '/unreachable/{print $3}'); do
      if GIT_DIR="$mod" git cat-file -p "$hash" 2>/dev/null | grep -q 'secret\['; then
        echo "STILL FOUND in submodule $mod: $(GIT_DIR="$mod" git cat-file -t "$hash" 2>/dev/null) $hash"
        touch /tmp/secret_still_found
      fi
    done
  done
fi

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
  ├─ Phase 1: Survey repo structure (branches, tags, stash, reflogs, replace refs, submodules)
  │
  ├─ Phase 2.0a: Quick check — working tree and index
  │   └─ Found? → Extract secret → Go to cleanup
  │
  ├─ Phase 2.0b: Unified scan — ALL objects in one pass
  │   └─ Found? → Note object type (blob/commit/tag) and reachability
  │       ├─ Reachable blob → Phase 2.0c: discover filename → Cleanup 3e + 3h
  │       ├─ Unreachable blob → No filename needed → Cleanup 3a + 3h
  │       ├─ Commit object → Secret in commit message → Cleanup 3e (--msg-filter) + 3h
  │       ├─ Tag object → Secret in tag annotation → Cleanup 3d + 3h
  │       └─ In stash ref → Cleanup 3b + 3h
  │
  ├─ Phase 2.1: Submodule scan (if .git/modules/ exists)
  │   └─ Run unified scan pattern against each submodule's object database
  │
  ├─ Write secret to /app/secret.txt
  │
  ├─ Phase 3: Cleanup (based on location) + Phase 3h: Universal cleanup
  │
  └─ Phase 4: Verify cleanup (re-run unified scan — covers all object types)
```

## Key Principles

1. **Recovery before cleanup**: Always recover and save the secret before any
   destructive operations.
2. **Unified scan first**: A single pass over ALL objects (reachable + unreachable)
   finds the secret regardless of location. This is faster and more robust than
   trying each location separately. The union of `git rev-list --all --objects`
   and `git fsck --unreachable --no-reflogs` covers every object in the repo.
3. **The scan covers all object types**: `git cat-file -p` on a commit shows the
   commit message; on a tag it shows the annotation. The secret might be in a
   commit message or tag annotation, not just a file blob.
4. **Reflogs are the enemy of cleanup**: Git reflogs keep "deleted" objects alive.
   Always expire reflogs before gc.
5. **`--prune=now` is essential**: Default gc may keep objects for 2 weeks.
   Always use `--prune=now`.
6. **`--aggressive` for thoroughness**: Ensures all packs are repacked and
   unreachable objects are fully removed.
7. **Delete backup refs BEFORE gc**: `git filter-branch` stores original refs
   under `refs/original/` that still point to old commits containing the secret.
   As long as these refs exist, gc treats those commits as reachable and will
   NOT prune them. Always delete `refs/original/` before running gc.
8. **Preserve legitimate content**: Never delete branches, tags, or commits that
   don't contain the secret. When rewriting history, only remove the tainted
   content.
9. **Match cleanup tool to object type**: File content → `--invert-paths` or
   `--index-filter`. Commit messages → `--message-callback` or `--msg-filter`.
   Tag annotations → delete the tag. Blob content → `--blob-callback`. Using
   the wrong filter (e.g., `--index-filter` for a commit message) will silently
   fail to clean the secret.
10. **Discover filenames for reachable blobs**: The unified scan gives you a blob
    hash, but `--invert-paths` needs a filename. Use `git log --all
    --find-object=<hash> --name-only` to map blob → filename. Unreachable blobs
    don't need this — they're not in any commit's tree.
11. **Verify with the same unified scan**: Re-run the Phase 2 unified scan as
    your verification step. It checks ALL object types (blobs, commits, tags)
    whether reachable or unreachable, packed or loose. Also check submodule
    object databases if present.
12. **Multiple locations possible**: The secret might exist in more than one place
    (e.g., committed AND in a stash). Search exhaustively.
