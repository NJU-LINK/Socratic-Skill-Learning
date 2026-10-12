---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository and then surgically remove it
  from all Git storage locations while preserving legitimate content. Handles
  secrets hidden in unreachable blobs, stashes, reachable commit history,
  deleted branches, tags, replace refs, reflogs, and annotated tag objects.
---

# Git Leak Recovery

## Overview

A secret (format `secret[...]`) was accidentally introduced into a Git repository.
The task has three phases: **recover** the secret, **clean** it from all Git storage,
and **preserve** all legitimate repository content.

## Core Principle

**Always recover before destructive cleanup.** Operations like `git gc --prune=now`
and `git filter-branch` are irreversible. Extract and save the secret first.

## Phase 1: Survey the Repository

Before searching, understand the repo's topology and all reference types:

```bash
# Basic structure
git log --all --oneline --graph
git branch -a
git tag -l
git stash list
git notes list 2>/dev/null
git for-each-ref refs/replace/
git for-each-ref refs/original/   # left by filter-branch

# Reflogs (can keep commits/blobs reachable)
git reflog --all

# Working tree state
git status

# Submodules (each has its own object database)
git submodule status 2>/dev/null
ls .git/modules/ 2>/dev/null
```

This survey tells you which hiding spots are relevant. A repo with no stashes
means stash search is unnecessary; a repo with replace refs means those must be
inspected and potentially cleaned. Submodules have separate object stores that
must be searched independently.

## Phase 2: Locate the Secret

Search locations in **sequential escalation order**. Start with 2a; only proceed
to the next method if all prior methods found nothing. Do not run parallel
shotgun searches — that wastes tool calls.

The secret format is `secret[...]`.

### 2a. Unreachable objects (staged-then-removed, amended-away, reset-away)

When a file was `git add`-ed but never committed (or was committed then removed
by reset/amend), its blob becomes unreachable. Find it with:

```bash
git fsck --unreachable --no-reflogs 2>&1 | grep 'unreachable blob'
```

Then inspect each blob:

```bash
git cat-file -p <blob-sha>
```

Alternative: `git fsck --lost-found` writes recovered blobs to `.git/lost-found/other/`.

### 2b. Reachable commit history

If the secret was committed (and possibly later removed from the working tree
but still in history):

```bash
git log --all -p -S 'secret[' --diff-filter=ACDMR
```

Or search all blobs reachable from all refs:

```bash
git rev-list --objects --all | while read sha rest; do
  content=$(git cat-file -p "$sha" 2>/dev/null)
  if echo "$content" | grep -q 'secret\['; then
    echo "Found in $sha ($rest)"
    echo "$content"
  fi
done
```

### 2c. Stashes

```bash
git stash list
# For each stash:
git stash show -p stash@{N} | grep 'secret\['
# Or inspect the stash commit's tree directly:
git cat-file -p stash@{N}
```

### 2d. Tags (especially annotated tags)

```bash
git tag -l | while read tag; do
  git cat-file -p "$tag" 2>/dev/null | grep 'secret\['
done
```

### 2e. Replace refs

```bash
git for-each-ref refs/replace/ | while read ref_type ref_sha ref_name; do
  git cat-file -p "$ref_sha" | grep 'secret\['
done
```

### 2f. Reflogs

Reflogs reference commits that may contain the secret. For each commit in the
reflog, inspect the blobs it introduced (the "new" side of each diff entry):

```bash
git reflog --all --format='%H' | while read sha; do
  git diff-tree --no-commit-id -r "$sha" 2>/dev/null | while read mode1 mode2 hash1 hash2 status path; do
    # $hash2 is the post-change blob; check it (and $hash1 for good measure)
    git cat-file -p "$hash2" 2>/dev/null | grep -q 'secret\[' && echo "Found via reflog in $sha (blob $hash2)"
    git cat-file -p "$hash1" 2>/dev/null | grep -q 'secret\[' && echo "Found via reflog in $sha (blob $hash1)"
  done
done
```

Note: `git cat-file -p` takes exactly one argument. Do not pass two hashes at once.

### 2g. Fast binary pre-check on pack files

Pack files are binary, but `strings` extracts readable runs. This is much faster
than enumerating every object and is an excellent first pass:

```bash
strings .git/objects/pack/*.pack | grep 'secret\['
```

If this finds the secret, you know it exists in a pack but still need to identify
which blob SHA contains it (use method 2h below).

### 2h. All objects (comprehensive fallback)

If the above miss the secret, enumerate every object in the object database:

```bash
# Loose objects
find .git/objects -type f | grep -v '/info/' | grep -v '/pack/' | while read f; do
  sha=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  git cat-file -p "$sha" 2>/dev/null | grep -q 'secret\[' && echo "Found in loose $sha"
done

# Packed objects
git verify-pack -v .git/objects/pack/*.idx 2>/dev/null | awk '/blob/{print $1}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q 'secret\[' && echo "Found in pack $sha"
done
```

## Phase 3: Recover the Secret

Once found, extract the secret string and write it. Pay attention to trailing
newlines: `git cat-file -p` outputs the blob content verbatim. If the blob ends
with a newline, the test may expect one in the output file.

```bash
# Safest approach: write the blob content directly to the output file,
# then verify in the SAME command (chained with &&) to avoid race conditions
git cat-file -p <blob-sha> > /app/secret.txt && cat /app/secret.txt

# Or if you extracted the string manually and know it has no trailing newline:
echo -n 'secret[...]' > /app/secret.txt && cat /app/secret.txt
```

**Decision rule**: The safest approach is always `git cat-file -p <sha> > /app/secret.txt`.
This writes the blob's exact bytes — no newline inspection needed. `xxd` is not
always available in containers; do not rely on it. Only use `echo -n` if you
have already manually inspected the blob and confirmed it has no trailing newline.

**Critical**: Always verify the output file in the SAME shell command (using `&&`)
or in a subsequent turn. Never run the redirect and the verification `cat` as
parallel tool calls — the `cat` may execute before the redirect completes,
showing an empty file and causing wasted debugging.

## Phase 4: Clean Up the Secret

The cleanup strategy depends on **where** the secret lives. Apply only the
relevant operations.

### 4a. Unreachable blobs (staged-then-removed, orphaned)

```bash
git reflog expire --expire=now --all
git gc --prune=now
```

This expires all reflogs (which can indirectly keep objects alive) and then
force-prunes all unreachable objects immediately.

### 4b. Stashes containing the secret

```bash
git stash drop stash@{N}
# Then also expire reflogs and gc to remove the underlying objects:
git reflog expire --expire=now --all
git gc --prune=now
```

### 4c. Secret in reachable commit history

This requires history rewriting. Use `git filter-repo` (preferred) or `git filter-branch`.

**`git filter-repo` availability**: Not installed by default. Install with
`pip install git-filter-repo` or fall back to `git filter-branch`.

```bash
# Using git filter-repo (if available):
git filter-repo --strip-blobs-with-ids <(echo "<blob-sha>")

# Or using git filter-branch:
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <path-to-secret-file>' \
  -- --all

# Then clean up filter-branch backup refs and all unreachable objects:
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --prune=now
```

**`--prune-empty` caution**: Adding `--prune-empty` to `filter-branch` will
delete any commit that becomes empty after the secret file is removed. This is
dangerous if a legitimate commit happened to only touch the secret file — that
commit (and its message) would be silently lost. **Omit `--prune-empty`** to
preserve commit structure, or if you use it, verify the resulting commit graph
with `git log --all --oneline` to confirm no legitimate commits were dropped.

**Important**: When rewriting history, ensure legitimate content in other files
and commits is preserved. Verify with `git log --all --stat` after rewriting.

### 4d. Secret in a tag

```bash
git tag -d <tag-name>
git reflog expire --expire=now --all
git gc --prune=now
```

### 4e. Secret in a replace ref

```bash
git update-ref -d refs/replace/<original-sha>
git reflog expire --expire=now --all
git gc --prune=now
```

### 4f. Secret in a deleted branch's reflog

```bash
git reflog expire --expire=now --all
git gc --prune=now
```

### 4g. Clean up `.git/lost-found/` if it exists

If `git fsck --lost-found` was used during recovery, remove the resulting
directory — tests check that it does not remain:

```bash
rm -rf .git/lost-found/
```

### 4h. General cleanup (always do after any specific cleanup)

Regardless of the secret's location, always finish with:

```bash
git reflog expire --expire=now --all
git gc --prune=now
```

This ensures any dangling references or orphaned objects from the cleanup
process itself are also removed.

## Phase 5: Verify

### 5a. No unreachable objects remain

```bash
git fsck --unreachable --no-reflogs 2>&1
# Should produce no "unreachable blob" lines
```

### 5b. Secret not in any reachable object

```bash
# Use `|| true` to prevent grep exit code 1 from breaking && chains
git rev-list --objects --all | while read sha rest; do
  git cat-file -p "$sha" 2>/dev/null
done | { grep -c 'secret\[' || true; }
# Should output 0
```

### 5c. Legitimate content preserved

```bash
git log --all --oneline    # All legitimate commits present
git branch -a              # All branches intact
git tag -l                 # Legitimate tags preserved
git status                 # Clean working tree
cat <legitimate-files>     # Content unchanged
```

## Decision Flowchart

```
Survey repo → Identify which locations exist
  ↓
Search all existing locations for secret[...]
  ↓
Found? → Extract to /app/secret.txt
  ↓
Where was it found?
  ├─ Unreachable blob → reflog expire + gc --prune=now
  ├─ Stash → stash drop + reflog expire + gc
  ├─ Reachable history → filter-repo/filter-branch + clean refs + gc
  ├─ Tag → tag -d + gc
  ├─ Replace ref → update-ref -d + gc
  └─ Reflog only → reflog expire + gc
  ↓
Verify: fsck clean, no secret in objects, legitimate content intact
```

## Common Pitfalls

1. **Running gc before recovery**: `git gc --prune=now` destroys unreachable objects permanently. Always extract the secret first.
2. **Forgetting reflogs**: Reflogs keep commits (and their trees/blobs) reachable. Must expire reflogs before gc to fully remove objects.
3. **Missing packed objects**: After gc, objects move from loose files into pack files. Search must cover both.
4. **Filter-branch backup refs**: `git filter-branch` creates `refs/original/` backups that still contain the secret. Must delete these before final gc.
5. **Annotated tag objects**: An annotated tag is itself a Git object (type `tag`) that can contain arbitrary text. Must inspect tag objects, not just the commits they point to.
6. **Submodule object databases**: In repos with submodules, check `.git/modules/<name>/objects/` as well. Each submodule has its own object store.
7. **`git cat-file -p` takes one argument**: Passing two SHAs silently fails or errors. Always invoke with a single SHA.
8. **`--prune-empty` can destroy legitimate commits**: See Phase 4c. Omit it unless you have verified the commit graph afterward.
9. **Trailing newline mismatch**: The secret blob may or may not end with `\n`. Use `git cat-file -p <sha> > file` to preserve exact content — no inspection needed.
10. **`grep -c` exit code 1 in `&&` chains**: `grep -c` returns exit code 1 when count is 0, which breaks `&&` chains. Always use `{ grep -c ... || true; }` or `;` instead of `&&` after grep.
11. **`.git/lost-found/` must be cleaned**: If `git fsck --lost-found` was used, `rm -rf .git/lost-found/` before finishing — tests check for its absence.
12. **Sequential search, not parallel**: Try 2a first; only escalate to 2b-2h if 2a finds nothing. Avoid running multiple search methods in parallel.
13. **Redirect-verify race condition**: When writing `git cat-file -p <sha> > file`, always verify with `&& cat file` in the same command. Running them as parallel tool calls causes the `cat` to execute before the redirect completes, showing an empty file and wasting debug calls.
