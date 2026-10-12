---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository's storage (reachable or unreachable objects,
  reflogs, stashes, replace refs, tags, branches) and then fully purge it from the repo
  while preserving all legitimate content.
---

# Git Leak Recovery

A secret (pattern `secret[...]`) was introduced into the Git repo at `/app/repo`.
Recover it to `/app/secret.txt`, purge every trace, and preserve all legitimate content.

Run each phase as **one single `task_shell` call**. Do not split phases across multiple calls.

---

## Phase 1 — Discover (one call)

Paste this entire block into a single `task_shell` invocation:

```bash
cd /app/repo

# --- Topology ---
echo "=== TOPOLOGY ==="
git branch -a; git tag -l; git remote -v
git log --all --oneline --graph --decorate
git stash list
ls -R .git/refs/ 2>/dev/null; true
cat .git/packed-refs 2>/dev/null; true
for f in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  [ -f ".git/$f" ] && echo "$f: $(cat .git/$f)"
done; true

# --- Scan every Git object for the secret ---
echo ""; echo "=== SCAN ==="
FOUND_IN=""

# Dangling / unreachable objects (robust SHA extraction via grep)
for sha in $(git fsck --unreachable --no-reflogs 2>&1 | grep -oE '[0-9a-f]{7,40}'); do
  type=$(git cat-file -t "$sha" 2>/dev/null) || continue
  if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
    echo "UNREACHABLE $type: $sha"
    git cat-file -p "$sha"
    FOUND_IN="$FOUND_IN unreachable:$sha"
  fi
done; true

# All reachable objects
for sha in $(git rev-list --all --objects 2>/dev/null | awk '{print $1}'); do
  if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
    echo "REACHABLE $(git cat-file -t "$sha"): $sha"
    FOUND_IN="$FOUND_IN reachable:$sha"
  fi
done; true

# Stash entries
SC=$(git stash list | wc -l)
if [ "$SC" -gt 0 ]; then
  for i in $(seq 0 $((SC - 1))); do
    if git stash show -p "stash@{$i}" 2>/dev/null | grep -qF 'secret['; then
      echo "STASH: stash@{$i}"
      FOUND_IN="$FOUND_IN stash:$i"
    fi
  done
fi; true

# Loose object scan
for d in .git/objects/??; do
  p=$(basename "$d")
  for f in "$d"/*; do
    [ -f "$f" ] || continue
    sha="${p}$(basename $f)"
    if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
      echo "LOOSE $(git cat-file -t $sha): $sha"
      FOUND_IN="$FOUND_IN loose:$sha"
    fi
  done
done; true

echo ""; echo "FOUND_IN=$FOUND_IN"
echo "=== DONE ==="
```

**Read the output.** Identify:
- The exact secret string (e.g. `secret[some_value]`)
- Whether the secret appears in `unreachable`, `reachable`, `stash`, or only `loose` objects
- If reachable: which **file path** inside the commit tree contains the secret
  (run `git log -p --all -S 'secret['` if needed to find the filename)

---

## Phase 2 — Recover (one call)

```bash
printf '%s' 'secret[EXACT_VALUE]' > /app/secret.txt
cat /app/secret.txt
```

Use `printf '%s'` to avoid trailing newline.

---

## Phase 3 — Purge (one call)

The purge path depends on what Phase 1 found. Choose **one** of:

### Path A: Dangling blob only (no reachable history, no stash)

```bash
cd /app/repo

# Clear stash, refs (harmless no-ops)
git stash clear 2>/dev/null; true
for ref in $(git for-each-ref --format='%(refname)' refs/replace/ refs/original/ 2>/dev/null); do
  git update-ref -d "$ref"
done; true
for tag in $(git tag -l 2>/dev/null); do
  if git cat-file -p "$(git rev-parse "$tag")" 2>/dev/null | grep -qF 'secret['; then
    git tag -d "$tag"
  fi
done; true

# Expire reflogs, then aggressive prune
git reflog expire --expire=now --all
git gc --prune=now --aggressive 2>&1

# Safety net: remove lingering loose tainted objects
for d in .git/objects/??; do
  p=$(basename "$d")
  for f in "$d"/*; do
    [ -f "$f" ] || continue
    sha="${p}$(basename $f)"
    if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
      rm -f "$f"
    fi
  done
done; true

echo "=== PURGE DONE (path A) ==="
```

### Path B: Secret in reachable commit history

Use this when Phase 1 showed `REACHABLE` containing the secret. You need the
**filename** of the leaked file (from `git log -p --all -S 'secret['`).

```bash
cd /app/repo
LEAKED_FILE="<filename>"   # e.g. "config.env" or "secret.txt"

# Drop stash
git stash clear 2>/dev/null; true

# Remove special refs
for ref in $(git for-each-ref --format='%(refname)' refs/replace/ refs/original/ 2>/dev/null); do
  git update-ref -d "$ref"
done; true

# Delete tainted tags
for tag in $(git tag -l 2>/dev/null); do
  if git cat-file -p "$(git rev-parse "$tag")" 2>/dev/null | grep -qF 'secret['; then
    git tag -d "$tag"
  fi
done; true

# Rewrite history to remove the leaked file
GIT_COMMITTER_NAME="$(git config user.name)" \
GIT_COMMITTER_EMAIL="$(git config user.email)" \
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch '$LEAKED_FILE'" \
  --prune-empty -- --all

# Remove backup refs created by filter-branch
for ref in $(git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null); do
  git update-ref -d "$ref"
done; true

# Expire reflogs
git reflog expire --expire=now --all

# Aggressive gc
git gc --prune=now --aggressive 2>&1

# Repack to purge secret from pack files
git repack -a -d 2>/dev/null; true
git prune-packed 2>/dev/null; true

# Safety net: remove lingering loose tainted objects
for d in .git/objects/??; do
  p=$(basename "$d")
  for f in "$d"/*; do
    [ -f "$f" ] || continue
    sha="${p}$(basename $f)"
    if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
      rm -f "$f"
    fi
  done
done; true

echo "=== PURGE DONE (path B) ==="
```

### Path C: Secret in a stash only

```bash
cd /app/repo
git stash clear
git reflog expire --expire=now --all
git gc --prune=now --aggressive 2>&1
for d in .git/objects/??; do
  p=$(basename "$d")
  for f in "$d"/*; do
    [ -f "$f" ] || continue
    sha="${p}$(basename $f)"
    if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
      rm -f "$f"
    fi
  done
done; true
echo "=== PURGE DONE (path C) ==="
```

### Decision: Which path?

| Phase 1 FOUND_IN contains… | Use Path |
|-----------------------------|----------|
| `unreachable:` or `loose:` only (no `reachable:`, no `stash:`) | A |
| `reachable:`                                  | B |
| `stash:` only (no `reachable:`)               | C |
| Both `reachable:` and `stash:`                | B (stash clear is included in B) |

When in doubt, run **Path B** — it covers all cases. The only extra cost is
filter-branch (harmless if no file matches) and repack.

---

## Phase 4 — Verify (one call)

```bash
cd /app/repo
LEAK=0

# V1: Unreachable
for sha in $(git fsck --unreachable --no-reflogs 2>&1 | grep -oE '[0-9a-f]{7,40}'); do
  git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret[' && { echo "FAIL unreachable: $sha"; LEAK=1; }
done; true
echo "V1 unreachable: done"

# V2: Reachable
for sha in $(git rev-list --all --objects 2>/dev/null | awk '{print $1}'); do
  git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret[' && { echo "FAIL reachable: $sha"; LEAK=1; }
done; true
echo "V2 reachable: done"

# V3: All loose objects
for d in .git/objects/??; do
  p=$(basename "$d")
  for f in "$d"/*; do
    [ -f "$f" ] || continue
    sha="${p}$(basename $f)"
    git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret[' && { echo "FAIL loose: $sha"; LEAK=1; }
  done
done; true
echo "V3 loose: done"

# V4: Pack files
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] || continue
  for sha in $(git verify-pack -v "$idx" 2>/dev/null | awk 'NF>1 && $1~/^[0-9a-f]{40}$/{print $1}'); do
    git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret[' && { echo "FAIL pack: $sha"; LEAK=1; }
  done
done; true
echo "V4 pack: done"

# V5: Stash
[ -z "$(git stash list)" ] || { echo "FAIL: stash not empty"; LEAK=1; }
echo "V5 stash: done"

# V6: Reflogs
git reflog --all 2>&1 | grep -qF 'secret[' && { echo "FAIL: reflog"; LEAK=1; }
echo "V6 reflogs: done"

# V7: Legitimate content
echo "V7 content:"
git log --all --oneline
git branch -a
git status

# V8: Secret file
echo "V8 secret.txt:"
cat /app/secret.txt

echo ""
[ "$LEAK" = "0" ] && echo "=== ALL CLEAN ===" || echo "=== LEAKS FOUND ==="
```

If output shows `ALL CLEAN`, the task is complete. If `LEAKS FOUND`, re-run Phase 3.

---

## Edge Cases

- **Submodules**: Repeat Phases 1 and 3 inside each `.git/modules/<name>` directory.
- **Multiple leak locations**: Path B handles stash + reachable + unreachable simultaneously.
- **`packed-refs`**: `git for-each-ref` handles both loose and packed refs transparently.
- **`filter-branch` complains about missing env vars**: The `GIT_COMMITTER_NAME` and
  `GIT_COMMITTER_EMAIL` exports in Path B handle this. If `user.name`/`user.email`
  are not set, use any placeholder value.
- **Secret appears in commit message or author field**: filter-branch with
  `--msg-filter` or `--env-filter` instead of `--index-filter`.
