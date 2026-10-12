---
name: git-leak-recovery
description: >
  Recover a leaked secret hidden somewhere in a Git repository's storage
  (objects, refs, reflogs, stashes, history, tags, replace refs, pack files),
  write it to a specified output file, then fully purge all traces of the secret
  from the repository while preserving legitimate content.
---

# Git Leak Recovery

## Task Summary

1. **Recover** a leaked secret from a Git repo and write it to an output file.
2. **Purge** every trace of the secret from the repo's Git storage.
3. **Preserve** all legitimate branches, commits, files, tags, and messages.

## Step 0 — Read Parameters from task.yaml

| Parameter | Source | Example value |
|-----------|--------|---------------|
| Repo path | Hint section | `/app/repo` |
| Secret format | Hint section | `secret[...]` |
| Output file path | Instruction step 1 | `/app/secret.txt` |

### Adapting the secret format to a grep pattern

The task gives a **human-readable format** (e.g. `secret[...]`). Convert it to
a working grep regex and grep -o extraction pattern:

| Format hint | grep -q pattern | grep -o extraction |
|-------------|-----------------|-------------------|
| `secret[...]` | `'secret\['` | `'secret\[[^]]*\]'` |
| `KEY=...` | `'KEY='` | `'KEY=[^ ]*'` |
| `token: ...` | `'token: '` | `'token: [^ ]*'` |
| literal string | the string itself | the string itself |

Use the **grep -o pattern** in extraction commands (Step 2) and the **grep -q
pattern** in search/verification commands.

---

## Step 1 — Find the Secret

Start with the fast path. Only run extended discovery if the fast path finds
nothing.

### Fast path (covers most cases)

```bash
cd <repo-path>

# Find unreachable/dangling objects
git fsck --unreachable --no-reflogs 2>&1
git fsck --dangling 2>&1

# Read each reported object
git cat-file -p <hash>
```

If you see the secret → go to **Step 2a** (dangling blob cleanup).

If `fsck` reports nothing, or the secret is not in those objects → run
**Extended discovery** below.

### Extended discovery (run only if fast path fails)

```bash
cd <repo-path>

# A) Search all reachable blob objects
git rev-list --all --objects 2>/dev/null | awk '{print $1}' | while read h; do
  [ "$(git cat-file -t "$h" 2>/dev/null)" = "blob" ] && \
    git cat-file -p "$h" 2>/dev/null | grep -q '<GREP_Q_PATTERN>' && \
    echo "REACHABLE blob $h"
done

# B) Search history diffs (committed then deleted)
git log --all -p -S '<GREP_Q_PATTERN>' 2>/dev/null

# C) Search reflog commits
git log -g --all -p -S '<GREP_Q_PATTERN>' 2>/dev/null

# D) Check stash entries
git stash list 2>/dev/null
# For each stash@{N}: git stash show -p stash@{N}

# E) Check special refs and HEAD files
find .git/refs -type f 2>/dev/null
for f in .git/MERGE_HEAD .git/ORIG_HEAD .git/FETCH_HEAD .git/CHERRY_PICK_HEAD; do
  [ -f "$f" ] && echo "$f: $(cat "$f")"
done

# F) Check lost-found directory
find .git/lost-found -type f 2>/dev/null

# G) Check pack file blobs
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] || continue
  git verify-pack -v "$idx" 2>/dev/null | awk '/^[0-9a-f]/{print $1}' | while read h; do
    [ "$(git cat-file -t "$h" 2>/dev/null)" = "blob" ] && \
      git cat-file -p "$h" 2>/dev/null | grep -q '<GREP_Q_PATTERN>' && \
      echo "PACK blob $h"
  done
done

# H) Check for nested/submodule repos
find . -name ".git" -not -path "./.git" 2>/dev/null
```

### Location → cleanup routing

| Where the secret was found | Go to |
|---------------------------|-------|
| Unreachable / dangling blob | **Step 2a** |
| Committed in branch history | **Step 2b** |
| In a stash entry | **Step 2c** |
| In special refs / lost-found | **Step 2d** |
| Multiple locations | Handle **each**, then **Step 3** |

---

## Step 2 — Recover & Clean Up

### 2a. Dangling / unreachable blob

```bash
# 1. Extract the secret (use grep -o to get ONLY the secret string)
git cat-file -p <blob-hash> | grep -o '<GREP_O_PATTERN>' > <output-path>

# 2. Verify extraction BEFORE any destructive cleanup
cat <output-path>

# 3. Expire all reflogs (MUST come before gc)
git reflog expire --expire=now --all

# 4. Prune unreachable objects
git gc --prune=now

# 5. Fallback: if gc didn't remove the blob, use git prune directly
git prune --expire=now
```

> ⚠️ **Order is critical**: `reflog expire` → `gc --prune=now` → `prune`.
> If you run `gc` before `reflog expire`, the blob may survive in a pack file.
> `git prune` is a belt-and-suspenders fallback that directly removes loose
> unreachable objects.

If the blob's full content is **exactly** the secret (no surrounding text),
you can write it directly: `git cat-file -p <blob-hash> > <output-path>`.
If the file contained the secret **among other content**, always use
`grep -o` to extract just the matching string.

### 2b. Secret committed in reachable history

```bash
# 1. Extract the secret first
git show <commit>:<path> | grep -o '<GREP_O_PATTERN>' > <output-path>
cat <output-path>  # verify

# 2. Rewrite history to remove the tainted file
git filter-branch --force \
  --index-filter 'git rm --cached --ignore-unmatch <secret-file>' \
  --prune-empty -- --all
# Or if git-filter-repo is installed: git filter-repo --invert-paths --path <secret-file> --force

# 3. If the secret is embedded inside a file (not a standalone file):
git filter-branch --force \
  --tree-filter "sed -i '/<GREP_Q_PATTERN>/d' <file> 2>/dev/null || true" \
  --prune-empty -- --all

# 4. Clean up filter-branch artifacts
rm -rf .git/refs/original
rm -f .git/refs/replace/*
git reflog expire --expire=now --all
git gc --prune=now
git prune --expire=now
```

**Preserving legitimate content**: After rewriting, verify:
```bash
git branch -a          # all branches still exist
git log --all --oneline  # commit messages preserved
git tag -l             # tags preserved
```

### 2c. Secret in a stash

```bash
# Extract
git stash show -p stash@{N} | grep -o '<GREP_O_PATTERN>' > <output-path>
cat <output-path>  # verify

# Remove
git stash drop stash@{N}
git reflog expire --expire=now refs/stash
git gc --prune=now
git prune --expire=now
```

### 2d. Secret behind special refs or lost-found

```bash
# Extract the secret content first

# Replace ref
git update-ref -d refs/replace/<name>
# Backup ref
rm -f .git/refs/original/<path>
# lost-found directory
rm -rf .git/lost-found

# Then purge
git reflog expire --expire=now --all
git gc --prune=now
git prune --expire=now
```

---

## Step 3 — Verify Complete Purge

Run this verification block. **Every check must return clean (no LEAK output).**

```bash
cd <repo-path>

echo "=== Unreachable ==="
git fsck --unreachable --no-reflogs 2>&1   # must produce no output

echo "=== Dangling ==="
git fsck --dangling 2>&1                    # must produce no output

echo "=== Reachable objects ==="
git rev-list --all --objects 2>/dev/null | awk '{print $1}' | \
  while read h; do git cat-file -p "$h" 2>/dev/null; done | \
  grep -c '<GREP_Q_PATTERN>'               # must be 0

echo "=== Loose objects ==="
find .git/objects -type f | grep -v '/pack/' | grep -v '/info/' | while read f; do
  hash=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  git cat-file -p "$hash" 2>/dev/null | grep -q '<GREP_Q_PATTERN>' && \
    echo "LEAK loose $hash"
done

echo "=== lost-found ==="
ls .git/lost-found 2>/dev/null && echo "LEAK: lost-found exists"

echo "=== Special HEADs ==="
for f in .git/MERGE_HEAD .git/ORIG_HEAD .git/FETCH_HEAD; do
  [ -f "$f" ] && echo "LEAK: $f exists"
done

echo "=== Binary search ==="
grep -rl '<GREP_Q_PATTERN>' .git/ 2>/dev/null && echo "LEAK: binary match"
```

### If any LEAK is found

| Problem | Fix |
|---------|-----|
| Unreachable object remains | Re-run `git reflog expire --expire=now --all && git gc --prune=now && git prune --expire=now` |
| Loose object survives gc | `git prune --expire=now` (directly removes loose objects) |
| Object in pack file | `git repack -a -d --no-reuse-delta && git gc --prune=now && git prune --expire=now` |
| lost-found remains | `rm -rf .git/lost-found` |
| Annotated tag references secret | `git tag -d <tagname>` then re-prune |

Re-run the full verification block after any fix.

---

## Step 4 — Verify Legitimate Content Preserved

```bash
git branch -a          # all branches intact
git tag -l             # all tags intact
git log --all --oneline  # commit history preserved
git status             # working tree clean
ls -la                 # expected files present
cat README.md          # or check whichever legitimate file should exist
```

If history was rewritten (Step 2b), confirm branch names, commit messages,
and file contents for non-tainted content match their expected state.
