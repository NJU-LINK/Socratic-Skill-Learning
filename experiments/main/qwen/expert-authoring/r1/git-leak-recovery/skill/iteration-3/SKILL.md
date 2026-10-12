---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository's object storage, metadata, or
  references, write it to a designated output file, then fully purge every
  recoverable trace of the secret while preserving all legitimate repository
  content (branches, tags, files, commit messages).
---

# Git Leak Recovery

## Goal

1. **Recover** the leaked secret → write to `/app/secret.txt`.
2. **Clean** every trace from the repo (objects, refs, reflogs, packs).
3. **Preserve** all legitimate branches, tags, files, and commit messages.

Repo location: `/app/repo`.

## Step 0 — Read the Pattern from task.yaml

The secret pattern is defined in `task.yaml` (e.g. `secret[...]`). Read it before
searching and use that exact pattern for all grep/search commands below. Never
assume the pattern — always derive it from the task definition.

---

## Step 1 — Find the Secret

### Quick-find (try this first)

```bash
cd /app/repo

# Unreachable / dangling objects — most common hiding place
git fsck --unreachable --no-reflogs 2>&1

# For each SHA reported, check its content:
git cat-file -p <SHA>
```

If `fsck` reports no unreachable objects, or none contain the secret, proceed
to exhaustive search.

### Exhaustive search (fallback)

Search **every** object in the repo — loose, packed, and reachable:

```bash
cd /app/repo

# Collect all object SHAs
{
  # Loose objects
  find .git/objects -type f | grep -vE '/pack/|/info/' \
    | sed 's|.git/objects/||;s|/||'
  # Packed objects
  for idx in .git/objects/pack/*.idx; do
    [ -f "$idx" ] && git verify-pack -v "$idx" 2>/dev/null \
      | awk '/^[0-9a-f]/ {print $1}'
  done
  # Reachable objects (includes trees, commits, blobs)
  git rev-list --all --objects 2>/dev/null | awk '{print $1}'
  # Stash commits
  git stash list --format='%H' 2>/dev/null
  # Reflog commits (may reference dropped branches/amends)
  git reflog --all --format='%H' 2>/dev/null
} | sort -u | while read sha; do
  [ "$(git cat-file -t "$sha" 2>/dev/null)" = "blob" ] || continue
  content="$(git cat-file -p "$sha" 2>/dev/null)"
  if printf '%s' "$content" | grep -qF '<PATTERN>'; then
    echo "FOUND blob $sha"
    printf '%s\n' "$content"
  fi
done
```

Also search commit messages, tag annotations, reachable diffs, and the filesystem:

```bash
# All reachable history diffs (every blob version that ever existed)
# Use grep -F for fixed-string matching — git log -G treats patterns as regex!
git log --all -p 2>/dev/null | grep -F '<PATTERN>'

# Commit messages and bodies
git log --all --format='%H %s %b' | grep -F '<PATTERN>'

# Annotated tag objects
git tag -l | while read t; do
  [ "$(git cat-file -t "$t" 2>/dev/null)" = "tag" ] && \
    git cat-file -p "$t" | grep -F '<PATTERN>' && echo "LEAK in tag $t"
done

# Index (currently staged blobs)
git ls-files --stage | while read _ sha _ path; do
  git cat-file -p "$sha" 2>/dev/null | grep -qF '<PATTERN>' && \
    echo "LEAK in index: $path ($sha)"
done

# Raw filesystem search — catches secrets in hooks, config, non-object files
grep -rF '<PATTERN>' .git/ --include='*' -l 2>/dev/null | grep -v '/objects/' | grep -v '/logs/'
```

### Additional locations to check

| Location | Command |
|---|---|
| Stash content | `git stash list` then `git stash show -p stash@{N}` |
| Replace refs | `git replace --list 2>/dev/null` |
| Backup refs (filter-branch leftovers) | `find .git/refs/original -type f 2>/dev/null` |
| Special HEAD files | `cat .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD 2>/dev/null` |
| Submodule object DBs | `find . -name ".git" -not -path "./.git"` — check each |

### Write the secret

```bash
echo -n '<EXACT_SECRET_STRING>' > /app/secret.txt
```

---

## Step 2 — Clean the Secret

Apply **only** the subsections (A–F) that match your findings. Skip what doesn't apply.

**Then always run the mandatory final cleanup** at the end, regardless of which
subsections you used.

### A. Secret only in unreachable objects (dangling blobs/commits/trees)

No history rewrite needed. Skip directly to the mandatory final cleanup.

### B. Secret in reachable commits (on a branch)

Rewrite history to remove the tainted file from every commit's tree:

```bash
# Single file
git filter-branch --force \
  --index-filter 'git rm --cached --ignore-unmatch <LEAKED_FILE> || true' \
  --prune-empty -- --all

# Multiple leaked files — chain the rm commands
git filter-branch --force \
  --index-filter '
    git rm --cached --ignore-unmatch file1 || true
    git rm --cached --ignore-unmatch file2 || true
  ' \
  --prune-empty -- --all
```

### C. Secret embedded in commit messages or tag annotations

```bash
# Rewrite commit messages containing the pattern
git filter-branch --force \
  --msg-filter 'sed "s/<PATTERN>/[REDACTED]/g"' \
  -- --all

# Delete tainted annotated tags
git tag -d <TAG_NAME>
```

### D. Secret in stash

```bash
# Drop a specific stash entry (drop highest index first to avoid shifting)
git stash drop stash@{N}

# Or clear all stashes
git stash clear
```

### E. Secret in replace refs or other special refs

```bash
git replace --delete <REF> 2>/dev/null
# Remove any other tainted refs manually
rm -f .git/refs/<path_to_ref>
```

### F. Submodules

```bash
git submodule foreach '
  rm -rf .git/refs/original
  git reflog expire --expire=now --all
  git gc --prune=now --aggressive
  git prune --expire=now
'
```

### MANDATORY — Final cleanup (always run, even for path A)

These four commands must run **every time**, in this exact order. Skipping any
of them leaves recoverable traces.

```bash
# 1. Remove backup refs — catches filter-branch leftovers AND pre-existing
#    refs/original that might reference tainted objects. Harmless if absent.
rm -rf .git/refs/original

# 2. Expire ALL reflogs — reflogs hold SHAs that prevent gc from pruning.
#    Without this step, dangling objects remain recoverable.
git reflog expire --expire=now --all

# 3. Aggressive gc — repacks reachable objects and prunes unreachable ones.
git gc --prune=now --aggressive

# 4. Direct prune — removes any remaining loose unreachable objects.
git prune --expire=now
```

---

## Step 3 — Verify

Every check below must produce **no output containing the pattern**.
If any check finds the secret, go back to Step 2.

```bash
cd /app/repo

# --- Object-level search (loose + packed) ---
{
  find .git/objects -type f | grep -vE '/pack/|/info/' \
    | sed 's|.git/objects/||;s|/||'
  for idx in .git/objects/pack/*.idx; do
    [ -f "$idx" ] && git verify-pack -v "$idx" 2>/dev/null \
      | awk '/^[0-9a-f]/ {print $1}'
  done
} | sort -u | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -qF '<PATTERN>' && \
    echo "LEAK: $sha"
done

# --- Reachable history ---
git grep -F '<PATTERN>' $(git rev-list --all) 2>/dev/null && echo "LEAK in reachable history"

# --- Index ---
git ls-files -s | while read _ sha _ path; do
  git cat-file -p "$sha" 2>/dev/null | grep -qF '<PATTERN>' && \
    echo "LEAK in index: $path"
done

# --- Stash ---
git stash list --format='%H' 2>/dev/null | while read sha; do
  git stash show -p "$sha" 2>/dev/null | grep -qF '<PATTERN>' && \
    echo "LEAK in stash $sha"
done

# --- Reflogs (should be empty after expire) ---
git reflog --all 2>/dev/null | grep -F '<PATTERN>' && echo "LEAK in reflog"

# --- fsck (should report nothing unreachable) ---
git fsck --unreachable --no-reflogs 2>&1 | grep -v "^$"

# --- Backup refs (should not exist after rm -rf) ---
test -d .git/refs/original && echo "WARNING: refs/original still exists"

# --- Raw filesystem search (catches non-object leaks: hooks, config, etc.) ---
grep -rF '<PATTERN>' .git/ --include='*' -l 2>/dev/null | grep -v '/objects/' | grep -v '/logs/'
```

---

## Step 4 — Verify Legitimate Content Preserved

```bash
git branch -a        # expected branches exist
git tag -l           # expected tags exist
git ls-files         # expected files tracked
git log --all --oneline  # commit messages intact
git status           # working tree clean
```

---

## Decision Rules

| Secret location | Cleanup subsection | Then mandatory final cleanup |
|---|---|---|
| Dangling / unreachable blob or commit | (none — skip A–F) | Yes |
| Reachable commit on a branch | B (filter-branch) | Yes |
| Stash entry | D (stash drop/clear) | Yes |
| Annotated tag | C (tag -d) | Yes |
| Replace ref | E (replace --delete) | Yes |
| Reflog-only reference | (none — skip A–F) | Yes (reflog expire handles it) |
| Multiple locations | Each applicable subsection | Yes (once, at the end) |
| Secret in commit message / tag text | C (msg-filter or tag -d) | Yes |

## Pitfalls

- **Always expire reflogs BEFORE gc.** Reflogs hold SHAs that prevent pruning.
- **`git gc` alone won't remove reachable tainted commits.** Rewrite or delete
  the referencing branch/tag first.
- **`rm -rf .git/refs/original` is NOT optional.** Even if you didn't run
  filter-branch, pre-existing backup refs can hide tainted objects.
- **`git prune` only removes loose objects.** Packed tainted objects need
  `--aggressive` gc or explicit `git repack -a -d`.
- **Submodules have separate object databases.** Clean each independently.
- **`git rm --cached --ignore-unmatch` exits non-zero if file isn't in tree.**
  Use `|| true` in index-filter to avoid aborting the rewrite.
- **`git log -G` treats patterns as regex** — `secret[` will crash with
  "invalid regex" due to unmatched `[`. Always use `grep -F` or
  `git grep -F` for fixed-string matching.
- **`git grep` needs `$(git rev-list --all)` which can overflow on huge repos.**
  For very large repos, use `git log --all -p | grep -F '<PATTERN>'` instead.
