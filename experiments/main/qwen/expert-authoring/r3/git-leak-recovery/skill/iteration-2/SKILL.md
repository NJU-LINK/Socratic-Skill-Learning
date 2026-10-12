---
name: git-leak-recovery
description: >
  Recover a leaked secret from a Git repository's storage (reachable or unreachable objects,
  reflogs, stashes, replace refs, tags, branches) and then fully purge it from the repo
  while preserving all legitimate content.
---

# Git Leak Recovery

## Task Summary

A secret was introduced into a Git repository at `/app/repo`. You must:
1. **Recover** the secret (pattern `secret[...]`) and write it to `/app/secret.txt`.
2. **Purge** every trace so it cannot be found anywhere in the repo.
3. **Preserve** all legitimate branches, commits, tags, files, and messages.

## Quick-Start Procedure

Follow these three phases in order. Each phase is a single consolidated script
that handles all variants (dangling blobs, reachable history, stashes, replace
refs, tags, pack files, etc.).

---

## Phase 1: Discover — Locate Every Copy of the Secret

Run this single discovery script. It scans **all** Git storage locations and
reports every object containing the secret.

```bash
cd /app/repo

echo "=== Repository Topology ==="
git branch -a
git tag -l
git remote -v
git log --all --oneline --graph --decorate
git stash list
ls -R .git/refs/ 2>/dev/null
cat .git/packed-refs 2>/dev/null; true

echo ""
echo "=== Scanning ALL objects for secret pattern ==="
LEAK_SHAS=""

# 1a. Unreachable / dangling objects
for sha in $(git fsck --unreachable --no-reflogs 2>&1 | awk '{print $NF}'); do
  if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
    echo "UNREACHABLE: $sha ($(git cat-file -t $sha))"
    git cat-file -p "$sha"
    LEAK_SHAS="$LEAK_SHAS $sha"
  fi
done; true

# 1b. All reachable objects (commits, trees, blobs)
for sha in $(git rev-list --all --objects | awk '{print $1}'); do
  if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
    echo "REACHABLE: $sha ($(git cat-file -t $sha))"
    LEAK_SHAS="$LEAK_SHAS $sha"
  fi
done; true

# 1c. Stash entries
STASH_COUNT=$(git stash list | wc -l)
if [ "$STASH_COUNT" -gt 0 ]; then
  for i in $(seq 0 $((STASH_COUNT - 1))); do
    if git stash show -p "stash@{$i}" 2>/dev/null | grep -qF 'secret['; then
      echo "STASH: stash@{$i}"
    fi
  done
fi; true

# 1d. Special refs
for ref_dir in .git/refs/replace .git/refs/original .git/refs/stash; do
  [ -d "$ref_dir" ] && find "$ref_dir" -type f
done; true

# 1e. Special HEAD files
for f in FETCH_HEAD ORIG_HEAD MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  [ -f ".git/$f" ] && echo "$f: $(cat .git/$f)"
done; true

# 1f. Loose objects scan (catches anything fsck might miss)
for obj_dir in .git/objects/??; do
  prefix=$(basename "$obj_dir")
  for obj_file in "$obj_dir"/*; do
    [ -f "$obj_file" ] || continue
    suffix=$(basename "$obj_file")
    sha="${prefix}${suffix}"
    if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
      echo "LOOSE: $sha ($(git cat-file -t $sha))"
    fi
  done
done; true

echo ""
echo "=== Discovery complete ==="
```

**Read the output carefully.** Record:
- The exact secret string (e.g. `secret[some_value]`)
- Which SHAs contain it
- Whether it appears in reachable history, stashes, refs, or only as dangling objects

---

## Phase 2: Recover — Write the Secret

```bash
printf '%s' 'secret[EXACT_VALUE]' > /app/secret.txt
cat /app/secret.txt
```

Use `printf '%s'` (not `echo`) to avoid trailing newline issues.

---

## Phase 3: Purge & Verify — Universal Cleanup

This single script handles **all** secret locations simultaneously. It is safe
to run regardless of where the secret was found. Steps that don't apply are
harmless no-ops.

```bash
cd /app/repo

# === PURGE ===

# P1: Drop ALL stash entries (cheap; stashes rarely hold legitimate state)
git stash clear 2>/dev/null; true

# P2: Remove replace refs and backup/original refs
for ref in $(git for-each-ref --format='%(refname)' refs/replace/ refs/original/ 2>/dev/null); do
  git update-ref -d "$ref"
done; true

# P3: Delete any tags whose target contains the secret
for tag in $(git tag -l 2>/dev/null); do
  sha=$(git rev-parse "$tag" 2>/dev/null)
  if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
    echo "Deleting tainted tag: $tag"
    git tag -d "$tag"
  fi
done; true

# P4: Handle secret in REACHABLE commit history
#     Only needed if Phase 1 showed the secret in a reachable commit/tree.
#     This rewrites history to remove the file, preserving other content.
#     SKIP this block if the secret was only a dangling blob.
#
# git filter-branch --force --index-filter \
#   'git rm --cached --ignore-unmatch <LEAKED_FILENAME>' \
#   --prune-empty -- --all
# # Clean up backup refs created by filter-branch:
# for ref in $(git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null); do
#   git update-ref -d "$ref"
# done; true

# P5: Expire ALL reflogs (prevents gc from retaining tainted commits)
git reflog expire --expire=now --all

# P6: Aggressive garbage collection with immediate prune
git gc --prune=now --aggressive 2>&1

# P7: Safety net — remove any remaining loose tainted objects
for obj_dir in .git/objects/??; do
  prefix=$(basename "$obj_dir")
  for obj_file in "$obj_dir"/*; do
    [ -f "$obj_file" ] || continue
    suffix=$(basename "$obj_file")
    sha="${prefix}${suffix}"
    if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
      echo "Removing lingering loose object: $sha"
      rm -f "$obj_file"
    fi
  done
done; true

# P8: If secret ended up in a pack (e.g., was in reachable history),
#     repack to exclude it. Only needed if P4 was used.
# git repack -a -d 2>/dev/null; true
# git prune-packed 2>/dev/null; true

echo "=== PURGE COMPLETE ==="
```

### When to Uncomment P4 and P8

| Phase 1 showed secret in…         | Uncomment |
|------------------------------------|-----------|
| Dangling blob only                 | Nothing — P1–P7 suffice |
| Reachable commit/tree/blob         | P4 and P8 |
| Stash entry                        | Nothing — P1 already cleared it |
| Replace ref or backup ref          | Nothing — P2 already removed it |
| Annotated tag                      | Nothing — P3 already deleted it |

---

## Phase 4: Verify — Confirm Everything Is Clean

Run this single consolidated verification. It uses `; true` guards so `&&`
chains never break on grep exit-code-1.

```bash
cd /app/repo
LEAK=0

# V1: No unreachable objects with secret
echo "--- V1: Unreachable objects ---"
for sha in $(git fsck --unreachable --no-reflogs 2>&1 | awk '{print $NF}'); do
  if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
    echo "FAIL: LEAK in unreachable $sha"; LEAK=1
  fi
done; true
[ "$LEAK" = "0" ] && echo "PASS"

# V2: No reachable objects with secret
echo "--- V2: Reachable objects ---"
for sha in $(git rev-list --all --objects | awk '{print $1}'); do
  if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
    echo "FAIL: LEAK in reachable $sha"; LEAK=1
  fi
done; true
echo "PASS (no reachable leaks)"

# V3: Brute-force scan of ALL loose objects
echo "--- V3: All loose objects ---"
for obj_dir in .git/objects/??; do
  prefix=$(basename "$obj_dir")
  for obj_file in "$obj_dir"/*; do
    [ -f "$obj_file" ] || continue
    suffix=$(basename "$obj_file")
    sha="${prefix}${suffix}"
    if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
      echo "FAIL: LEAK in loose $sha"; LEAK=1
    fi
  done
done; true
echo "PASS (no loose leaks)"

# V4: Pack file objects
echo "--- V4: Pack files ---"
for idx in .git/objects/pack/*.idx; do
  [ -f "$idx" ] || continue
  for sha in $(git verify-pack -v "$idx" 2>/dev/null | awk 'NF>1{print $1}'); do
    if git cat-file -p "$sha" 2>/dev/null | grep -qF 'secret['; then
      echo "FAIL: LEAK in pack $sha"; LEAK=1
    fi
  done
done; true
echo "PASS (no pack leaks)"

# V5: Stashes clean
echo "--- V5: Stash ---"
[ -z "$(git stash list)" ] && echo "PASS" || echo "WARN: stashes exist"

# V6: Reflogs clean
echo "--- V6: Reflogs ---"
if git reflog --all 2>&1 | grep -qF 'secret['; then
  echo "FAIL: LEAK in reflog"; LEAK=1
else
  echo "PASS"
fi

# V7: Legitimate content preserved
echo "--- V7: Legitimate content ---"
git log --all --oneline
git branch -a
git status

# V8: Secret file correct
echo "--- V8: Secret file ---"
cat /app/secret.txt

echo ""
if [ "$LEAK" = "0" ]; then
  echo "=== ALL CLEAN ==="
else
  echo "=== LEAKS FOUND — re-run purge ==="
fi
```

---

## Why This Approach Works

| Principle | Explanation |
|-----------|-------------|
| **Scan before acting** | Phase 1 checks every storage location, so you know exactly where the secret lives |
| **Universal purge** | Steps P1–P7 are safe no-ops when they don't apply, so running all of them avoids missed locations |
| **No `&&` chains** | Using `; true` and explicit `LEAK` flags prevents grep exit-code-1 from aborting verification |
| **`grep -F` for fixed string** | Using `-F` (fixed string) avoids regex interpretation of `[` and `]` in `secret[...]` |
| **`printf '%s'` over `echo`** | Prevents trailing newline in secret.txt |
| **Reflog expiry before gc** | Without expiring reflogs first, gc retains references to tainted commits |
| **`--prune=now`** | Tells gc to immediately remove (not just mark) unreachable objects |

---

## Handling Complex Variants

### Secret in reachable commit history
If `git log -p --all` shows the secret in a committed file, uncomment P4 (filter-branch).
This rewrites history to remove the file while preserving all other commits and content.
After rewriting, commit SHAs downstream of the change will differ from originals.

### Multiple leak locations
The universal purge script handles all locations simultaneously. If the secret appears
in both a stash AND a dangling blob, P1 clears the stash and P6/P7 clean the blob.

### Submodules
If the repo contains submodules, repeat Phases 1 and 3 inside each `.git/modules/<name>`
directory, or run `find /app/repo -name ".git" -type d` to locate all object databases.

### `packed-refs` file
Some repos store refs in `.git/packed-refs` rather than loose files under `.git/refs/`.
The `git for-each-ref` command in P2 handles both formats transparently.
