---
name: git-leak-recovery
description: >
  Recover leaked secrets from Git repositories and clean them from all storage
  locations (dangling blobs, stashes, reachable history, deleted branches,
  replace refs, tags, submodules). Works across varying repo complexities and
  cleanup scopes.
---

# Git Leak Recovery

## Overview

When a secret is accidentally introduced into a Git repository, it persists in
multiple layers of Git's object model even after superficial removal. This skill
provides a systematic pipeline to:

1. **Discover** where the secret lives
2. **Recover** its value
3. **Clean** it from every storage layer
4. **Verify** complete removal while preserving legitimate content

## Decision Tree: Which Cleanup Path?

Based on what you find in discovery, choose the appropriate cleanup:

**Found unreachable blob/commit/tree?**
→ Expire reflogs + prune objects (see Cleanup Phase steps 3-4)

**Found secret in stash?**
→ `git stash drop stash@{N}` then expire reflogs + prune

**Found secret in reachable history (committed)?**
→ Rewrite history with `git filter-repo` (see Cleanup Phase step 2) then expire reflogs + prune

**Found secret in replace ref?**
→ `git replace -d <ref>` then expire reflogs + prune

**Found secret in annotated tag?**
→ `git tag -d <tag-name>` (only if tag contains secret) then expire reflogs + prune

**Multiple locations?**
→ Remove structural refs first (stash/replace/tag) → rewrite history if needed → expire reflogs → prune

## Discovery Phase

### Quick-Start: Consolidated Discovery Sweep

Run this single command to check the most common hiding places at once:

```bash
cd /app/repo
echo "=== UNREACHABLE OBJECTS ===" && git fsck --unreachable --no-reflogs 2>&1
echo "=== STASH ===" && git stash list 2>&1
echo "=== REPLACE REFS ===" && git replace --list 2>&1
echo "=== TAGS ===" && git tag -l 2>&1
echo "=== REACHABLE SECRET SEARCH ===" && git log --all -p -S 'secret[' 2>&1
```

This covers 80% of cases. If you find the secret, skip to **Recovery Phase**. If not, continue below for advanced locations.

### Advanced Discovery (If Quick-Start Finds Nothing)

**1. Dangling/Unreachable Objects** (most common for staged-but-not-committed secrets)

```bash
git fsck --unreachable --no-reflogs 2>&1
```

- `--unreachable` reports objects not reachable from any ref or index
- `--no-reflogs` is critical: reflogs keep objects "reachable" even when no branch points to them
- Look for `unreachable blob`, `unreachable commit`, `unreachable tree`

### 2. Stash (Live)

```bash
git stash list
```

If stashes exist, inspect each:
```bash
git stash show -p stash@{N}
```

### 3. Reachable History (Committed)

Search all branches and tags for the secret pattern:
```bash
git log --all -p -S 'secret[' 
# or more broadly:
git log --all -p | grep -C 3 'secret\['
```

### 4. Replace Refs

```bash
git replace --list
```

If replace refs exist, inspect the replaced objects:
```bash
git cat-file -p <original-sha>
```

### 5. Tags (Especially Annotated)

```bash
git tag -l
# For each tag:
git cat-file -t <tag-name>  # "tag" means annotated
git cat-file -p <tag-name>  # Read tag object
```

### 6. Reflog (Previous HEAD positions)

```bash
git reflog
# Shows where HEAD pointed over time
# Each entry is a commit SHA that may have been reset away
```

### 7. Submodule Object Databases

```bash
cat .gitmodules 2>/dev/null
# For each submodule, run discovery in its directory
```

### 8. Pack Files

```bash
ls .git/objects/pack/
# If pack files exist, verify their contents:
for p in .git/objects/pack/*.idx; do
  [ -f "$p" ] && git verify-pack -v "$p" | grep blob
done
```

## Recovery Phase

Once you've identified candidate SHAs, inspect them:

```bash
git cat-file -p <sha>
```

For commits, walk their trees:
```bash
git cat-file -p <commit-sha>^{tree}
# Then inspect blobs in the tree:
git cat-file -p <blob-sha>
```

Match against the secret pattern (e.g., `secret[...]`). Write the recovered value:

```bash
echo -n 'secret[value]' > /app/secret.txt
```

### Handling Multiple Unreachable Objects

When `git fsck` reports multiple unreachable objects, systematically scan each:

```bash
# Parse fsck output and inspect each object by type
git fsck --unreachable --no-reflogs 2>&1 | grep "unreachable" | while read _ type sha; do
  case "$type" in
    blob)
      # Inspect blob directly
      content=$(git cat-file -p "$sha" 2>/dev/null)
      echo "$content" | grep -q 'secret\[' && echo "FOUND in blob $sha: $content"
      ;;
    commit)
      # Walk the commit's tree to find blobs
      tree_sha=$(git cat-file -p "$sha" 2>/dev/null | grep "^tree" | awk '{print $2}')
      if [ -n "$tree_sha" ]; then
        git ls-tree "$tree_sha" 2>/dev/null | while read mode type blob_sha filename; do
          if [ "$type" = "blob" ]; then
            content=$(git cat-file -p "$blob_sha" 2>/dev/null)
            echo "$content" | grep -q 'secret\[' && echo "FOUND in blob $blob_sha (from commit $sha): $content"
          fi
        done
      fi
      ;;
    tree)
      # List blobs in the tree
      git ls-tree "$sha" 2>/dev/null | while read mode type blob_sha filename; do
        if [ "$type" = "blob" ]; then
          content=$(git cat-file -p "$blob_sha" 2>/dev/null)
          echo "$content" | grep -q 'secret\[' && echo "FOUND in blob $blob_sha (from tree $sha): $content"
        fi
      done
      ;;
  esac
done
```

**Why parse by type?** Unreachable commits and trees don't contain the secret directly — you must walk their trees to find the blobs inside. This handles:
- Multiple dangling blobs (several staged files, only one has the secret)
- Unreachable commits (from reset-away branches)
- Unreachable trees (intermediate directory states)

## Cleanup Phase

**Order matters.** Remove structural references first, then expire reflogs, then prune.

### 1. Remove Structural References

**Stashes:**
```bash
git stash drop stash@{N}
```

**Replace refs:**
```bash
git replace -d <ref>
```

**Tainted tags (only if the tag itself contains the secret):**
```bash
git tag -d <tag-name>
```

### 2. Rewrite Reachable History (If Secret Was Committed)

If the secret exists in committed history, you must rewrite commits:

**Using git-filter-repo (preferred):**
```bash
git filter-repo --blob-callback '
import re
if re.search(b"secret\\[", blob.data):
    blob.data = re.sub(b"secret\\[[^\\]]*\\]", b"[REDACTED]", blob.data)
'
```

> **Why pattern-based, not literal?** By discovery time you know the exact secret value, but using `re.search`/`re.sub` with the pattern is more robust: it handles variants where the exact value differs, catches multiple occurrences, and generalizes to "redact anything matching this format." The `import re` goes inside the callback string since each invocation is a standalone Python snippet.

**Using git-filter-branch (fallback):**
```bash
git filter-branch --tree-filter '
  if [ -f secret.txt ]; then
    sed -i "s/secret\[.*\]//g" secret.txt
  fi
' --all
```

**Warning:** This changes commit SHAs. Preserve file content and commit messages of legitimate commits.

### 3. Expire Reflogs

```bash
git reflog expire --expire=now --all
```

This removes all reflog entries, making previously "reachable" objects truly unreachable.

### 4. Prune Unreachable Objects

```bash
git prune --expire=now
git gc --prune=now --aggressive
```

**Why both?** `git prune` removes unreachable loose objects. `git gc --aggressive` repacks remaining objects and ensures pack files are clean. Running both is belt-and-suspenders but ensures complete removal.

This physically removes unreachable objects from `.git/objects/`.

## Verification Phase

**Critical:** Use `;` separators (not `&&`) so all checks run even if one fails.

```bash
cd /app/repo
echo "=== 1. Blob removed ==="
git cat-file -p <original-secret-sha> 2>&1 || echo "(expected: fatal error)"
echo "=== 2. No unreachable objects ==="
git fsck --unreachable --no-reflogs 2>&1
echo "(empty = clean)"
echo "=== 3. No secret in .git ==="
grep -r 'secret\[' .git/ 2>/dev/null || echo "(none found = clean)"
echo "=== 4. Legitimate commits preserved ==="
git log --oneline --all
echo "=== 5. Branches intact ==="
git branch -a
echo "=== 6. Files intact ==="
cat README.md
```

All checks should pass:
- Secret blob no longer exists (cat-file errors)
- No unreachable objects in fsck
- No `secret[` pattern in `.git/`
- All legitimate commits, branches, and files preserved

## Common Pitfalls

1. **Using `&&` chains for verification:** If one command fails (e.g., `git cat-file` on a deleted blob returns 128), subsequent checks won't run. Use `;` or separate commands.

2. **Forgetting `--no-reflogs`:** Without this flag, `git fsck` won't report objects that reflogs keep alive.

3. **Cleaning up before recovering:** Always recover the secret first. Cleanup is destructive.

4. **Assuming `git prune` is sufficient:** Prune only removes unreachable objects. If the secret is in reachable history, you must rewrite commits first.

5. **Not checking pack files:** Secrets can persist in pack files even after pruning loose objects. Run `git gc` to repack and ensure secrets are removed.

6. **Deleting all tags:** Only delete tags that actually contain the secret. Legitimate tags should be preserved.

## Family Variations

### secret_location

- **Dangling blob** (v01): `git fsck --unreachable --no-reflogs` → `git cat-file -p`
- **Stash**: `git stash list` → `git stash show -p`
- **Reachable history**: `git log --all -p -S` → requires history rewriting
- **Deleted branch**: `git reflog` or `git fsck` → walk commit trees
- **Replace ref**: `git replace --list` → inspect replaced objects
- **Annotated tag**: `git tag -l` → `git cat-file -p <tag>`
- **Amended/reset commit**: `git reflog` → walk old commit trees
- **Submodule**: Run discovery in each submodule's `.git/`

### repo_complexity

- **Single branch, few commits** (v01): Simple fsck + prune
- **Multiple branches**: Check all branches with `git log --all`
- **Merges**: Walk merge commit trees carefully
- **Tags**: Inspect each tag object
- **Nested repos**: Recurse into submodules
- **Dozens of commits**: Use `-S` search to narrow down

### cleanup_scope

- **Dangling objects only**: `reflog expire` + `prune`
- **Stash**: `git stash drop` before prune
- **Reachable history**: Must rewrite commits (changes SHAs)
- **Replace refs**: `git replace -d`
- **Tags**: `git tag -d` for tainted tags only
- **Reflogs**: Always expire them
- **Pack files**: Run `git gc` to repack

## Example: Dangling Blob Scenario

**Scenario:** Secret was staged (`git add`), then removed from index without committing. Blob is dangling.

**Discovery:**
```bash
git fsck --unreachable --no-reflogs
# Output: unreachable blob <sha>
```

**Recovery:**
```bash
git cat-file -p <sha>
# Output: secret[...]
echo -n 'secret[...]' > /app/secret.txt
```

**Cleanup:**
```bash
git reflog expire --expire=now --all
git prune --expire=now
git gc --prune=now --aggressive
```

**Verification:**
```bash
git cat-file -p <sha> 2>&1 || echo "(expected: fatal error)"
git fsck --unreachable --no-reflogs  # Should be empty
grep -r 'secret\[' .git/  # Should find nothing
git log --oneline --all  # Legitimate commits preserved
```

## Key Principles

1. **Discover before cleanup:** Find all hiding places first.
2. **Recover before destroy:** Get the secret value before removing it.
3. **Systematic enumeration:** Check every layer (objects, stash, history, refs, tags, submodules).
4. **Order matters:** Remove structural refs → rewrite history → expire reflogs → prune.
5. **Verify thoroughly:** Check SHAs, fsck, grep, and legitimate content.
6. **Preserve legitimate content:** Don't delete branches, tags, or commits that don't contain the secret.
