---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository and then purge it from all
  Git storage and metadata, preserving legitimate branches, files, tags, and
  commit messages. Handles secrets hidden in unreachable blobs, stashes,
  reachable history, deleted branches, replace refs, backup refs, annotated
  tags, submodule object databases, and pack files.
---

# Git Leak Recovery

## Overview

A secret was accidentally introduced into a Git repository. The task is to:
1. **Recover** the secret value and write it to `/app/secret.txt`.
2. **Purge** it from every location in the repository so it cannot be recovered.
3. **Preserve** all legitimate content (branches, files, tags, commit messages).

The secret format is `secret[...]`. There is exactly one such string in the repo.

**Critical invariant**: Always recover the secret BEFORE any destructive cleanup.

## Phase 1: Survey — Locate the Secret

Run the **consolidated survey script** below inside the repo directory. This runs ALL checks in a single command and produces structured output with clear FOUND/NONE indicators.

**CRITICAL: You MUST run this entire survey script before proceeding to Phase 2.** Do not stop after finding the first hit. The secret may exist in multiple locations simultaneously, and missing a location means the cleanup will be incomplete.

```bash
#!/bin/bash
# Consolidated Git Leak Survey Script
# Runs all checks and produces structured output

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "=== GIT LEAK SURVEY REPORT ==="
echo ""

# 1a. Unreachable objects
echo "--- 1a. Unreachable Objects ---"
UNREACHABLE=$(git fsck --unreachable --no-reflogs 2>&1)
if [ -n "$UNREACHABLE" ]; then
  echo "$UNREACHABLE"
  UNREACHABLE_BLOBS=$(echo "$UNREACHABLE" | grep "unreachable blob" | awk '{print $3}')
  UNREACHABLE_COMMITS=$(echo "$UNREACHABLE" | grep "unreachable commit" | awk '{print $3}')
  echo "FOUND: blobs=[$UNREACHABLE_BLOBS] commits=[$UNREACHABLE_COMMITS]"
else
  echo "NONE"
fi
echo ""

# 1b. Live stashes
echo "--- 1b. Live Stashes ---"
STASHES=$(git stash list 2>&1)
if [ -n "$STASHES" ]; then
  echo "$STASHES"
  echo "FOUND: stashes exist"
else
  echo "NONE"
fi
echo ""

# 1c. All refs
echo "--- 1c. All Refs ---"
REFS=$(git for-each-ref --format='%(refname)' 2>&1)
echo "$REFS"
REPLACE_REFS=$(echo "$REFS" | grep "^refs/replace/" || true)
BACKUP_REFS=$(echo "$REFS" | grep -E "^refs/(original|backups)/" || true)
if [ -n "$REPLACE_REFS" ]; then echo "FOUND: replace refs"; fi
if [ -n "$BACKUP_REFS" ]; then echo "FOUND: backup refs"; fi
echo ""

# 1d. Reflog
echo "--- 1d. Reflog ---"
git reflog --all 2>&1
echo ""

# 1e/1f. Reachable history search
echo "--- 1e/1f. Reachable History Search ---"
REACHABLE=$(git grep 'secret\[' $(git rev-list --all) 2>/dev/null || true)
if [ -n "$REACHABLE" ]; then
  echo "$REACHABLE"
  echo "FOUND: secret in reachable history"
else
  echo "NONE"
fi
echo ""

# 1g. Submodules
echo "--- 1g. Submodules ---"
if [ -f .gitmodules ]; then
  cat .gitmodules
  echo "FOUND: submodules exist"
else
  echo "NONE"
fi
echo ""

# 1h. Pack files
echo "--- 1h. Pack File Scan ---"
PACK_FOUND=0
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] || continue
  while read sha; do
    if git cat-file -p "$sha" 2>/dev/null | grep -q 'secret\['; then
      echo "FOUND secret in pack object $sha"
      PACK_FOUND=1
    fi
  done < <(git verify-pack -v "$idx" 2>/dev/null | grep -E '^[0-9a-f]{40}' | awk '{print $1}')
done
if [ "$PACK_FOUND" -eq 0 ]; then
  echo "NONE"
fi
echo ""

echo "=== SURVEY COMPLETE ==="
```

### Survey Completeness Checklist

After running the survey script, confirm you see output for ALL of these sections:

- [ ] **1a.** Unreachable Objects — FOUND or NONE?
- [ ] **1b.** Live Stashes — FOUND or NONE?
- [ ] **1c.** All Refs — any replace/backup refs?
- [ ] **1d.** Reflog — any deleted branch entries?
- [ ] **1e/1f.** Reachable History Search — FOUND or NONE?
- [ ] **1g.** Submodules — FOUND or NONE?
- [ ] **1h.** Pack File Scan — FOUND or NONE?

**If any section is missing from the output, the script failed. Re-run it.**

### Classification

Based on which commands returned hits, classify the `secret_location`:

| Survey result | Secret location |
|---|---|
| `git fsck` shows unreachable blob(s) | **Unreachable blob** — staged then removed, never committed |
| `git fsck` shows unreachable commit(s) with stash-like parent structure | **Dropped stash** |
| `git stash list` is non-empty | **Live stash** |
| `git grep` finds the secret in a reachable commit | **Reachable history** — committed then removed |
| `git reflog` shows entries for deleted branches | **Deleted branch** (reflog still references it) |
| `git for-each-ref` shows `refs/replace/*` | **Replace ref** |
| `git for-each-ref` shows `refs/original/*` or `refs/backups/*` | **Backup ref** (from filter-branch or similar) |
| Annotated tag message or tagged object contains the secret | **Annotated tag** |
| Submodule `.git` directory contains the secret | **Submodule object database** |

Multiple locations may apply simultaneously. Handle each one.

## Phase 2: Recover — Extract the Secret

Use the appropriate read command for each location type:

### Unreachable blob
```bash
git cat-file -p <blob_sha>
```

### Dropped stash (unreachable commit)
```bash
# Stash commits have 2-3 parents. Read the tree of the stash commit.
git cat-file -p <stash_commit_sha>
# Then inspect the tree to find the secret file
git ls-tree -r <stash_commit_sha>
git cat-file -p <blob_sha_from_tree>
```

### Live stash
```bash
git stash show -p stash@{N}
# Or inspect the stash commit directly
git cat-file -p $(git rev-parse stash@{N})
```

### Reachable history
```bash
# Find which commit introduced the secret
git log --all -p -S 'secret[' -- <file_path>
# Extract from the specific commit
git show <commit_sha>:<file_path>
```

### Deleted branch (via reflog)
```bash
# The reflog entry still points to the commit
git show <reflog_sha>:<file_path>
# Or if the branch is gone but reflog remains
git log <reflog_sha> --oneline
```

### Replace ref
```bash
# The replace ref substitutes one object for another
git for-each-ref refs/replace/
# Read the replacement object
git cat-file -p <replacement_sha>
```

### Backup ref
```bash
git log refs/original/refs/heads/<branch> --oneline
git show <sha>:<file_path>
```

### Annotated tag
```bash
git cat-file -p <tag_name>
# Check both the tag message and the tagged object
git cat-file -p <tagged_object_sha>
```

### Submodule
```bash
cd <submodule_path>
git fsck --unreachable --no-reflogs
git cat-file -p <blob_sha>
```

Write the recovered secret (just the `secret[...]` string, no trailing newline issues) to `/app/secret.txt`:
```bash
echo '<secret_value>' > /app/secret.txt
```

## Phase 3: Clean — Purge the Secret

Apply cleanup strategies matched to each location. **Order matters**: remove references first, then expire reflogs, then gc.

### Unreachable blobs/commits (including dropped stashes)
```bash
git reflog expire --expire=now --all
git gc --prune=now
```

### Live stash
```bash
git stash drop stash@{N}
git reflog expire --expire=now --all
git gc --prune=now
```

### Reachable history (secret was committed)
**Preferred: `git filter-repo`** (faster, safer, no backup refs by default)
```bash
if command -v git-filter-repo &>/dev/null; then
  git filter-repo --invert-paths --path <tainted_file> --force
else
  # Fallback to git filter-branch (slower, creates refs/original/ backups)
  git filter-branch --index-filter \
    'git rm --cached --ignore-unmatch <tainted_file>' \
    --prune-empty -- --all
fi
```

After history rewrite:
```bash
# Remove backup refs created by filter-branch
git for-each-ref --format='%(refname)' refs/original/ | while read ref; do
  git update-ref -d "$ref"
done
# Expire reflogs and gc
git reflog expire --expire=now --all
git gc --prune=now
```

**Important**: History rewriting changes commit SHAs but preserves commit messages and file content (minus the tainted file). This is expected and correct.

### Replace ref
```bash
git update-ref -d refs/replace/<original_sha>
git reflog expire --expire=now --all
git gc --prune=now
```

### Backup ref
```bash
git update-ref -d refs/original/refs/heads/<branch>
git reflog expire --expire=now --all
git gc --prune=now
```

### Annotated tag containing the secret
```bash
git tag -d <tag_name>
git reflog expire --expire=now --all
git gc --prune=now
```

### Submodule
```bash
cd <submodule_path>
git reflog expire --expire=now --all
git gc --prune=now
cd ..
```

### Pack files still containing the secret
After gc, if the Phase 4 pack file verification (step 4g) still finds the secret in packed objects, the objects were not fully pruned. Re-run:
```bash
git repack -a -d --depth=250 --window=250
git gc --prune=now
```

## Phase 4: Verify — Confirm Purge and Preservation

**Re-run the same consolidated survey script from Phase 1.** All sections should now show NONE (except 1c All Refs which should still show legitimate branches, and 1d Reflog which may be empty after expiry).

Then run these additional targeted checks:

```bash
# 4c. Original blob is gone (if you know the SHA from Phase 1)
git cat-file -p <original_blob_sha> 2>&1
# Should return "fatal: Not a valid object name"

# 4d. Legitimate commits preserved
git log --all --oneline
# Should show all legitimate commits with correct messages

# 4e. Legitimate files preserved
git show HEAD:<file> 2>/dev/null
# Should show expected content

# 4f. Tags preserved (if any existed)
git tag -l

# 4i. Secret file exists with correct content
cat /app/secret.txt
```

**Note on `git fsck` stale data**: After `git gc --prune=now`, the first `git fsck --unreachable` call may still report objects that were just pruned. This is a known caching behavior. Run `git fsck` a second time to confirm — if the second run shows nothing, the cleanup succeeded. The consolidated survey script handles this correctly because it runs fsck as part of its normal flow.

## Decision Procedure Summary

```
SURVEY (consolidated script) → CLASSIFY (from report) → RECOVER → WRITE → CLEAN → VERIFY (re-run survey)

1. Run the consolidated survey script (ALL checks in one command)
2. Review the survey report — identify all FOUND locations
3. Classify secret_location from the report (may be multiple)
4. Extract secret using location-appropriate read command
5. Write to /app/secret.txt
6. Apply matched cleanup for EACH location (remove refs → expire reflogs → gc)
7. Re-run the consolidated survey script to confirm ALL sections show NONE
8. Run additional verification checks (commit log, file content, secret.txt)
```

## Pitfalls

- **Never clean before recovering.** `git gc --prune=now` is irreversible.
- **History rewriting changes SHAs.** This is expected; the task requires preserving messages and content, not SHAs.
- **`filter-branch` creates `refs/original/` backup refs.** Always delete these before gc, or the secret remains reachable.
- **Pack files can retain secrets after loose object cleanup.** Always verify packed objects with `git verify-pack -v` + `git cat-file -p` (do not rely on `strings`, which may be absent in minimal containers).
- **Reflogs can keep "deleted" objects reachable.** Always expire reflogs before gc.
- **Multiple locations may apply.** A secret could be in both reachable history AND an unreachable blob. Handle all hits.
- **Submodules have independent object databases.** Run the full procedure inside each submodule if applicable.
- **Bash subshell variable loss in pipelines.** When using `pipeline | while read`, the `while` loop runs in a subshell, so variable assignments (like `pack_found=1`) are lost when the loop ends. Use process substitution `while read ... done < <(pipeline)` instead to keep variables in the current shell. This affects any tracking variables in pack file scans.
- **`git fsck` stale data after gc.** After `git gc --prune=now`, the first `git fsck --unreachable` call may still report objects that were just pruned due to internal caching. Run `git fsck` a second time to confirm — if the second run shows nothing, the cleanup succeeded. Always verify with `git cat-file -p <sha>` to confirm the object is actually gone.
