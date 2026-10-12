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

Also search commit messages, tag annotations, and reachable diffs:

```bash
# Commit messages and bodies
git log --all --format='%H %s %b' | grep -F '<PATTERN>'

# Reachable diffs (shows every blob version that ever existed in history)
git log --all -p | grep -F '<PATTERN>'

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

Apply **only** the subsections that match your findings. Skip what doesn't apply.

### Order matters — always finish with expire + prune

Regardless of which cleanup steps you take, **always** end with:

```bash
# 1. Delete filter-branch backup refs (if you ran filter-branch)
rm -rf .git/refs/original

# 2. Expire ALL reflogs (prevents pruned objects from being resurrected)
git reflog expire --expire=now --all

# 3. Aggressive prune + repack (removes loose AND packed unreachable objects)
git gc --prune=now --aggressive
git prune --expire=now
```

### A. Secret only in unreachable objects (dangling blobs/commits/trees)

No history rewrite needed. Just expire + prune (above).

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

Then delete backup refs and expire + prune (above).

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

# --- Reachable history (git grep is faster and cleaner than log -p) ---
git grep -F '<PATTERN>' $(git rev-list --all) 2>/dev/null && echo "LEAK in reachable history"

# --- Index ---
git ls-files -s | while read _ sha _ path; do
  git cat-file -p "$sha" 2>/dev/null | grep -qF '<PATTERN>' && \
    echo "LEAK in index: $path"
done

# --- Stash ---
git stash list 2>/dev/null | while read line; do
  echo "$line" | grep -qF '<PATTERN>' && echo "LEAK in stash list"
done
git stash list --format='%H' 2>/dev/null | while read sha; do
  git stash show -p "$sha" 2>/dev/null | grep -qF '<PATTERN>' && \
    echo "LEAK in stash $sha"
done

# --- Reflogs ---
git reflog --all 2>/dev/null | grep -F '<PATTERN>' && echo "LEAK in reflog"

# --- fsck (should report nothing unreachable) ---
git fsck --unreachable --no-reflogs 2>&1

# --- Special refs ---
for f in .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD; do
  [ -f "$f" ] && grep -qF '<PATTERN>' "$f" && echo "LEAK in $f"
done

# --- Backup refs ---
find .git/refs/original -type f 2>/dev/null | while read f; do
  sha="$(cat "$f")"
  git cat-file -p "$sha" 2>/dev/null | grep -qF '<PATTERN>' && \
    echo "LEAK in backup ref $f"
done
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

| Secret location | Cleanup needed |
|---|---|
| Dangling / unreachable blob or commit | Expire reflogs + prune only |
| Reachable commit on a branch | filter-branch rewrite → delete backup refs → expire + prune |
| Stash entry | `git stash drop` or `clear` → expire + prune |
| Annotated tag | `git tag -d` → expire + prune |
| Replace ref | `git replace --delete` → expire + prune |
| Reflog-only reference | Expire reflogs → prune |
| Multiple locations | Handle each → single final expire + prune pass |
| Secret in commit message / tag text | filter-branch `--msg-filter` or delete tag → expire + prune |

## Pitfalls

- **Always expire reflogs BEFORE gc.** Reflogs hold SHAs that prevent pruning.
- **`git gc` alone won't remove reachable tainted commits.** Rewrite or delete
  the referencing branch/tag first.
- **filter-branch creates `.git/refs/original/`.** Delete it before pruning.
- **`git prune` only removes loose objects.** Packed tainted objects need
  `--aggressive` gc or explicit `git repack -a -d`.
- **Submodules have separate object databases.** Clean each independently.
- **`git rm --cached --ignore-unmatch` exits non-zero if file isn't in tree.**
  Use `|| true` in index-filter to avoid aborting the rewrite.
