---
name: git-leak-recovery
description: >
  Recover leaked secrets from Git repositories and perform thorough cleanup.
  Handles secrets in unreachable blobs, reflog-reachable commits, stashes
  (live/dropped), reachable history, special refs (replace, backup, stash),
  tags, and submodule object databases. Preserves legitimate repo content.
---

# Git Leak Recovery

## Overview

This skill recovers accidentally-leaked secrets from Git repositories and removes all traces. The secret format is typically `secret[...]`. The procedure works across all Git storage locations and repo topologies.

## Critical Invariant

**Recovery MUST complete before any cleanup.** Once objects are pruned, the secret is irrecoverable.

## General Procedure

### Phase 1: Survey the Repository

Understand the repo topology before touching anything:

```bash
# Basic topology
git branch -a
git tag -l
git stash list
git for-each-ref --format='%(refname) %(objecttype) %(objectname)' | sort

# Check for special refs
ls .git/refs/original/ 2>/dev/null
ls .git/refs/replace/ 2>/dev/null
cat .git/FETCH_HEAD .git/ORIG_HEAD .git/MERGE_HEAD 2>/dev/null

# Check for submodules
cat .gitmodules 2>/dev/null
ls .git/modules/ 2>/dev/null
```

### Phase 2: Detect the Secret in All Locations

#### Quick Triage: Which Detection Method to Try First

Use task description hints and repo survey results to prioritize detection:

| Task Description Hint | Likely Location | Try First |
|----------------------|----------------|-----------|
| "staged but never committed" | Unreachable blob | **2a** (git fsck) |
| "committed then reverted/deleted" | Reachable history | **2d** (git log -S) |
| "stashed" or "stash" | Stash (live or dropped) | **2c** (git stash list + fsck) |
| "reset" or "amended" | Reflog-reachable commit | **2b** (git reflog) |
| "deleted branch" | Reflog or unreachable commit | **2b** then **2a** |
| "filter-branch" or "replace" | Backup/replace refs | **2e** (git for-each-ref) |
| "tag" | Annotated tag | **2f** (git tag) |
| "submodule" | Submodule ODB | **2g** (check submodule) |
| No hints / ambiguous | Unknown | **2a** → **2b** → **2c** → **2d** → **2h** (catch-all) |

**Strategy**: Start with the method indicated by the hint. If not found, proceed through the remaining methods in order. Use **2h** (Raw Object Database Sweep) as a comprehensive catch-all if other methods fail.

---

### Two-Phase Detection: Recovery vs. Cleanup

**Phase 2A — Recovery-Scoped Detection (find the value):**
- Use Quick Triage to prioritize detection methods
- **Stop as soon as you have the secret string** — you only need one copy to recover the value
- Proceed to Phase 3 (Recover the Secret)

**Phase 2B — Cleanup-Scoped Detection (know all locations):**
After recovering the secret value, you MUST determine which locations reference the secret, because different locations require different cleanup actions:

| Location | Cleanup Action Required |
|----------|------------------------|
| Unreachable blob | `git gc --prune=now` (sufficient) |
| Reachable history (committed) | Step 4.3: `git filter-repo` / `git filter-branch` (history rewriting) |
| Reflog-reachable commit | Expire reflogs + `git gc` |
| Stash (live) | `git stash drop` + `git gc` |
| Tag | `git tag -d` + `git gc` |
| Special refs (replace/backup) | Delete ref + `git gc` |

**Critical post-recovery check** (run this after Phase 3):
```bash
# Does the secret exist in reachable history? (If yes → Step 4.3 is needed)
git log --all -S "secret[" --oneline 2>/dev/null
```

If this returns commits, **Step 4.3 (history rewriting) is required** regardless of where else the secret was found.

**Also check for other locations:**
```bash
# Check if secret is in any reachable object (not just commits)
git rev-list --all --objects | awk '{print $1}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "Found in reachable object $sha"
done

# Check stashes
git stash list  # If any exist, check them

# Check tags
git tag -l | while read tag; do
  git show "$tag" 2>/dev/null | grep -q "secret\[" && echo "Found in tag $tag"
done
```

**Decision**: If the secret exists in ANY reachable location (commits, tags, stashes), you must use the corresponding cleanup action. If it only exists in unreachable objects, `git gc --prune=now` is sufficient.

---

Search every possible storage location systematically. Use the known secret pattern (e.g., `secret[`) to locate it.

#### 2a. Unreachable/Dangling Blobs

These arise when a file was `git add`-ed then unstaged/deleted without ever being committed.

```bash
git fsck --unreachable --dangling --no-reflogs 2>&1 | grep -E "^(unreachable|dangling) blob" | awk '{print $NF}'
```

For each blob SHA found:
```bash
git cat-file -p <sha>
```

#### 2b. Reflog-Reachable Commits

Any branch movement (reset, amend, rebase) leaves old commits in the reflog.

```bash
git reflog --all --format='%H %gs'
```

For each commit SHA in the reflog:
```bash
git show <sha> --stat
git diff <sha>^ <sha> 2>/dev/null || git show <sha>  # for initial commits
```

Or search all reflog commits for the pattern:
```bash
git reflog --all --format='%H' | while read sha; do
  git log -1 -p "$sha" 2>/dev/null | grep -l "secret\[" && echo "Found in reflog commit $sha"
done
```

#### 2c. Stashes

Live stashes are visible via `git stash list`. Dropped stashes become dangling merge commits found by `git fsck`.

```bash
# Live stashes
git stash list
git stash show -p stash@{N}

# Dropped stashes (dangling commits from fsck)
git fsck --unreachable --dangling --no-reflogs 2>&1 | grep "commit" | awk '{print $NF}' | while read sha; do
  git show "$sha" 2>/dev/null | grep "secret\[" && echo "Found in dangling commit $sha"
done
```

#### 2d. Reachable History (Committed then Reverted)

```bash
# Search all reachable commits for the pattern
git log --all -S "secret[" -p
# Or search all diffs
git log --all -p | grep -B5 -A5 "secret\["
```

#### 2e. Special Refs

Replace refs, backup refs (from filter-branch), and stash refs can point to tainted objects.

```bash
# Replace refs
git for-each-ref refs/replace/ --format='%(objectname)' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep "secret\[" && echo "Found in replace ref $sha"
done

# Backup refs (filter-branch leftovers)
git for-each-ref refs/original/ --format='%(objectname)' | while read sha; do
  git log -1 -p "$sha" 2>/dev/null | grep "secret\[" && echo "Found in backup ref $sha"
done
```

#### 2f. Tags

Tags can point to commits or trees containing secrets.

```bash
git tag -l | while read tag; do
  git show "$tag" 2>/dev/null | grep "secret\[" && echo "Found in tag $tag"
done
```

#### 2g. Submodule Object Databases

Each submodule has its own `.git/modules/<name>/objects/`. Run the same detection procedure inside each submodule.

#### 2h. Raw Object Database Sweep

As a catch-all, enumerate ALL objects and search their content:

```bash
# All reachable objects
git rev-list --all --objects | awk '{print $1}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "FOUND in reachable object $sha"
done

# All objects including unreachable (from pack files and loose)
find .git/objects -type f | while read f; do
  # Extract SHA from path
  sha=$(echo "$f" | sed 's|.git/objects/||;s|/||')
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "FOUND in object $sha"
done
```

### Phase 3: Recover the Secret

Once located, extract the secret value and write it to the required output location (typically `/app/secret.txt`):

```bash
# For a blob:
git cat-file -p <blob_sha> > /app/secret.txt

# For content in a commit diff:
git show <commit_sha> -- <path> | grep "secret\[" > /app/secret.txt
```

**Confirm recovery before proceeding to cleanup.**

### Phase 3.5: Cleanup-Scoped Detection (Post-Recovery)

After recovering the secret value, you MUST determine which locations reference the secret to select correct cleanup actions. **Do not skip this step.**

**Critical check — does the secret exist in reachable history?**
```bash
# If this returns commits, Step 4.3 (history rewriting) is REQUIRED
git log --all -S "secret[" --oneline 2>/dev/null
```

**Also check other reachable locations:**
```bash
# Reachable objects (commits, trees, blobs)
git rev-list --all --objects | awk '{print $1}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "SECRET in reachable object $sha"
done

# Live stashes
git stash list  # If non-empty, check each: git stash show -p stash@{N} | grep "secret\["

# Tags
git tag -l | while read tag; do
  git show "$tag" 2>/dev/null | grep -q "secret\[" && echo "SECRET in tag $tag"
done
```

**Decision matrix:**
- If secret is in **reachable history** → Step 4.3 (history rewriting) is required
- If secret is in **reachable objects but not committed** (e.g., stash, tag) → delete that specific ref
- If secret is **only in unreachable objects** → Step 4.4-4.5 (expire reflogs + gc) is sufficient

### Phase 4: Cleanup (Ordered)

Remove the secret from every location. Order matters:

#### Step 4.1: Delete Special Refs Pointing to Tainted Objects

```bash
# Remove replace refs
git for-each-ref --format='%(refname)' refs/replace/ | xargs -r -n1 git update-ref -d

# Remove backup refs (filter-branch leftovers)
git for-each-ref --format='%(refname)' refs/original/ | xargs -r -n1 git update-ref -d

# Remove stash if tainted
git for-each-ref --format='%(refname)' refs/stash | xargs -r -n1 git update-ref -d
```

#### Step 4.2: Remove Tainted Tags

Only delete tags that reference tainted objects. Preserve legitimate tags.

```bash
# For each tainted tag:
git tag -d <tagname>
```

#### Step 4.3: Rewrite Reachable History (if secret was committed)

If the secret exists in reachable commit history, use `git filter-repo` (preferred) or `git filter-branch`:

```bash
# Using git filter-repo (requires git-filter-repo installed)
git filter-repo --strip-blobs-with-ids <blob_ids_file>

# Or using filter-branch
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch <path_to_secret_file>' \
  --prune-empty -- --all
```

**Warning**: History rewriting changes commit SHAs. This is destructive to shared history.

#### Step 4.4: Expire All Reflogs

Reflogs keep old commits reachable. Expire them all:

```bash
git reflog expire --expire=now --all
```

#### Step 4.5: Prune Unreachable Objects

```bash
# Simple approach (recommended): gc handles repack + prune internally
git gc --prune=now --aggressive

# OR explicit sequence (if you need more control):
# git repack -A -d -l  # Consolidate objects, remove unreachable from packs
# git prune --expire=now  # Remove loose unreachable objects
# git gc --prune=now --aggressive  # Final sweep
```

**Note**: `git gc --prune=now --aggressive` already performs repack and prune internally. The separate commands are only needed if you want to inspect intermediate state or need finer control.

#### Step 4.6: Handle Submodule Object Databases

If submodules contain the secret, repeat the cleanup procedure inside each submodule's git directory.

### Phase 5: Verify (Multi-Method)

Do not trust a single verification method. Use all of these.

**CRITICAL**: Use `;` (not `&&`) to chain verification steps. `grep` returns exit code 1 when it finds no matches, which is the *desired* outcome but would break an `&&` chain and make success look like failure.

#### 5a. fsck Check

```bash
git fsck --unreachable --dangling --no-reflogs 2>&1
# Should show NO unreachable blobs/commits, or at least none containing the secret
```

#### 5b. Reachable Object Sweep (PRIMARY — most reliable)

This is the most reliable check because `git cat-file -p` decompresses objects (including those in pack files) before searching.

```bash
git rev-list --all --objects | awk '{print $1}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "LEAK STILL PRESENT in $sha"
done
# Empty output = clean
```

#### 5c. Unreachable Object Sweep

After cleanup, there should be no unreachable objects containing the secret. If `git fsck` reports unreachable objects, check each one:

```bash
git fsck --unreachable --dangling --no-reflogs 2>&1 | grep -oE '[0-9a-f]{40}' | while read sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "LEAK in unreachable object $sha"
done
# Empty output = clean
```

#### 5d. Raw Filesystem Grep (supplementary only)

**Limitation**: This only finds secrets in *loose* objects and config files. It does NOT find secrets inside compressed pack files (`.git/objects/pack/*.pack`) because pack files use zlib compression. The `git cat-file` sweep (5b) is the reliable method for packed objects.

```bash
grep -rl "secret\[" .git/ 2>/dev/null || echo "(no matches in loose objects/config)"
```

#### 5e. Ref Verification

```bash
git for-each-ref --format='%(refname) %(objectname)' | while read ref sha; do
  git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "LEAK in ref $ref -> $sha"
done
# Empty output = clean
```

#### Combined Verification Block

Copy-paste this robust combined check (uses `;` separators, not `&&`):

```bash
echo "=== fsck ==="; git fsck --unreachable --dangling --no-reflogs 2>&1;
echo "=== reachable sweep ==="; git rev-list --all --objects | awk '{print $1}' | while read sha; do git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "LEAK in $sha"; done; echo "(empty = clean)";
echo "=== filesystem grep ==="; grep -rl "secret\[" .git/ 2>/dev/null || echo "(no matches in loose objects)";
echo "=== ref check ==="; git for-each-ref --format='%(refname) %(objectname)' | while read ref sha; do git cat-file -p "$sha" 2>/dev/null | grep -q "secret\[" && echo "LEAK in $ref"; done; echo "(empty = clean)";
echo "=== VERIFICATION COMPLETE ==="
```

### Phase 6: Preservation Check

Confirm legitimate content is intact:

```bash
# All branches still exist
git branch -a

# All legitimate tags still exist
git tag -l

# Commit messages unchanged (if history was not rewritten)
git log --oneline --all

# Working tree clean
git status

# Legitimate files present
ls -la
```

## Decision Points

| Situation | Action |
|-----------|--------|
| Secret only in unreachable blob | Recover via `git cat-file -p`, then `git gc --prune=now` |
| Secret in reflog commit | Recover from reflog commit, expire reflogs, then gc |
| Secret in live stash | Recover from stash, `git stash drop`, then gc |
| Secret in dropped stash | Find dangling commit via fsck, recover, then gc |
| Secret in reachable history | Recover, then `git filter-repo` or `git filter-branch` to rewrite |
| Secret in replace/backup ref | Delete the ref, then gc |
| Secret in tag | Delete the tag, then gc |
| Secret in submodule | Repeat entire procedure inside submodule |
| **Secret in multiple locations** | **Recover value first (any location), then run Phase 3.5 cleanup-scoped detection to identify ALL locations, then apply ALL applicable cleanup actions** |

## Edge Cases

- **Packed objects**: After `git gc`, objects are consolidated into pack files (`.git/objects/pack/`). Pack files use zlib compression, so raw `grep` on `.git/` will NOT find secrets inside them. The `git cat-file -p` sweep (Phase 5b) is reliable because it decompresses objects before searching. Always use 5b as the primary verification method.
- **Shallow clones**: May not have full history. Use `git fetch --unshallow` first if needed.
- **Bare repositories**: No working tree; all content is in objects. Adjust file checks accordingly.
- **Multiple secrets**: The procedure works for any number of secrets; just ensure all are recovered before cleanup.
- **Large repos**: The object-by-object sweep can be slow. Use `git grep` for reachable content and `git fsck` for unreachable content as faster alternatives.

## Reference Script

See `scripts/cleanup-and-verify.sh` for an automated cleanup and verification script.
