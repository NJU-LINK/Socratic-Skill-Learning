---
name: git-leak-recovery
description: Recover secrets from Git object databases and completely purge them while preserving legitimate repository state. Verified on unreachable blobs, stashes, staged files, and reachable file history; bounded on submodules, nested repos, and embedded secrets.
---

# Git Leak Recovery

Recover secrets from Git object databases and completely remove them while preserving legitimate repository state.

## Quick Start

```bash
bash /skill/scripts/recover-and-clean.sh <repo-path> <output-file> <secret-pattern>
```

Example:
```bash
bash /skill/scripts/recover-and-clean.sh /app/repo /app/secret.txt 'secret\['
```

**Note**: The script is located at `/skill/scripts/recover-and-clean.sh` in this environment. In other environments, use package-relative path `scripts/recover-and-clean.sh` from the skill root, or discover it via `find / -maxdepth 4 -name recover-and-clean.sh 2>/dev/null`.

## Verified Variants

| Location | Recovery | Cleanup | Status |
|----------|----------|---------|--------|
| Unreachable blob (staged-then-removed) | `git cat-file blob <oid>` | reflog expire + gc/prune | **Verified** |
| Index (staged file) | `git cat-file blob <oid>` | `git rm --cached <path>` | **Verified** |
| Live stash | object enumeration | `git stash drop <stash>` (highest first) | **Verified** |
| Reachable history (dedicated secret file) | enumeration | `git filter-branch --index-filter` | **Verified** |
| Tainted commit messages | extraction | `git filter-branch --msg-filter` | **Verified** |

## Bounded Variants (Mechanism Documented, Not Fully Verified)

| Location | Approach | Gap |
|----------|----------|-----|
| Submodule object DBs | Find `.git/modules/*/objects`, repeat procedure per gitdir | Not exercised in fixtures |
| Nested Git repositories | `find -name .git -type d`, enumerate each | Not exercised in fixtures |
| Embedded secret in legitimate file | `filter-branch --tree-filter` with sed | Not exercised in fixtures |

## Key Technical Facts

1. **Git objects are zlib-deflated** — Use `git cat-file --batch-all-objects` to enumerate all objects.

2. **Staged files** — The index pins objects; must `git rm --cached` before purge.

3. **RefLogs keep objects alive** — Must expire reflogs before gc; skip `refs/stash` to preserve legitimate stashes.

4. **Stash renumbering** — Drop highest indices first.

5. **Non-blob secrets** — Commit/tag messages may carry secrets; extract pattern match, not whole object.

## 5-Phase Procedure

### Phase A: Snapshot
```bash
SNAP_DIR=$(mktemp -d)
trap 'rm -rf "$SNAP_DIR"' EXIT

git log --all --format='%H %s' > "$SNAP_DIR/commits.txt"
git tag -l > "$SNAP_DIR/tags.txt"
git stash list > "$SNAP_DIR/stashes.txt"
git ls-files -s > "$SNAP_DIR/index.txt"
```

### Phase B: Discover & Recover
```bash
git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' | \
while read hash type; do
    git cat-file $type $hash | grep -q "$PATTERN" && echo "$hash $type"
done
```

**Recovery from blob:**
```bash
git cat-file blob <tainted-blob-hash> > "$OUTPUT_FILE"
```

**Recovery from commit/tag (pattern extraction):**
```bash
git cat-file -p <tainted-hash> | grep -aoE "$PATTERN[^]]*\]" | head -1 > "$OUTPUT_FILE"
```

### Phase C: Cut References

**Staged files:**
```bash
while read -r mode obj stage path; do
    if tainted "$obj"; then
        git rm --cached "$path"
    fi
done < <(git ls-files -s)
```

**Stashes:**
```bash
git stash list --format='%H %gd' | while read commit ref; do
    if git rev-list --objects "$commit" | grep -q tainted; then
        echo "$ref" >> "$STASH_DROP"
    fi
done
sort -rn "$STASH_DROP" | while read idx ref; do
    git stash drop "$ref"
done
```

**Reachable history (blobs):**
```bash
git filter-branch --index-filter 'git rm --cached --ignore-unmatch <path>' \
    --tag-name-filter cat -- --all
```

**Reachable history (commit messages):**
```bash
git filter-branch --msg-filter 'sed "s/$PATTERN[^]]*\]/REDACTED/g"' \
    --tag-name-filter cat -- --all
```

### Phase D: Purge
```bash
while read ref; do
    [[ "$ref" == "refs/stash" ]] && continue
    git reflog expire --expire=now --expire-unreachable=now "$ref"
done < <(git for-each-ref --format='%(refname)'; echo "HEAD")

git gc --prune=now
git prune --expire=now
```

### Phase E: Verify
```bash
# Zero secret matches
git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' | \
while read hash type; do
    git cat-file $type $hash | grep -q "$PATTERN" && exit 1
done

# Snapshot diff
git log --all --format='%s' | sort | diff <(sort "$SNAP_DIR/commits.txt" | cut -d' ' -f2-) -
```

## Script Reference

**Location in this environment:** `/skill/scripts/recover-and-clean.sh`

**Package-relative:** `scripts/recover-and-clean.sh`

**Usage:**
```bash
bash /skill/scripts/recover-and-clean.sh <repo-path> <output-file> <secret-pattern>
```

The script handles both blob and non-blob (commit/tag message) secrets, exiting loudly if extraction fails.
