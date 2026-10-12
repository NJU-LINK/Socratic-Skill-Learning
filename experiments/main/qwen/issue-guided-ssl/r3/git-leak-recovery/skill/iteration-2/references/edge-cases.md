# Edge Cases and Advanced Scenarios

## Dropped Stashes

When a stash is dropped (`git stash drop` or `git stash clear`), the stash commits become dangling. They are merge commits with 2-3 parents.

**Detection:**
```bash
git fsck --unreachable --dangling --no-reflogs 2>&1 | grep "commit"
```

**Recovery:**
```bash
# Each dangling commit SHA might be a dropped stash
git show <dangling-commit-sha>
# Look for the secret in the diff
```

**Cleanup:** After recovery, `git gc --prune=now` will remove these.

## Replace Refs

`git replace <original> <replacement>` creates a ref in `refs/replace/` that transparently substitutes objects. A secret could be hidden in a replacement object.

**Detection:**
```bash
git for-each-ref refs/replace/
```

**Cleanup:**
```bash
git for-each-ref --format='%(refname)' refs/replace/ | xargs -r -n1 git update-ref -d
```

## Filter-Branch Backup Refs

`git filter-branch` creates backup refs in `refs/original/` that point to the pre-rewrite history. If the original history contained a secret, these refs keep it reachable.

**Detection:**
```bash
git for-each-ref refs/original/
```

**Cleanup:**
```bash
git for-each-ref --format='%(refname)' refs/original/ | xargs -r -n1 git update-ref -d
```

## Annotated Tags Containing Secrets

An annotated tag object itself could contain a secret in its tag message, or it could point to a commit/tree/blob containing a secret.

**Detection:**
```bash
git tag -l | while read tag; do
  # Check tag message
  git tag -l --format='%(contents)' "$tag" | grep "secret\["
  # Check pointed-to object
  git rev-parse "$tag^{blob}" 2>/dev/null | xargs -r git cat-file -p | grep "secret\["
  git log -1 -p "$tag" 2>/dev/null | grep "secret\["
done
```

**Cleanup:** Delete only tainted tags:
```bash
git tag -d <tainted-tag>
```

## Submodule Object Databases

Submodules have independent git repositories with their own object databases at `.git/modules/<submodule-name>/`.

**Detection:** Run the full detection procedure inside each submodule:
```bash
for moddir in .git/modules/*/; do
  echo "Checking submodule: $moddir"
  GIT_DIR="$moddir" git fsck --unreachable --dangling --no-reflogs 2>&1
done
```

**Cleanup:** Run cleanup inside each submodule's git dir.

## Multiple Secrets in Different Locations

The procedure handles this naturally:
1. Detect ALL secrets across ALL locations first
2. Recover ALL of them
3. Then clean ALL locations

## Shallow Clones

Shallow clones may not have full history. Secrets in un-fetched commits won't be visible.

**Solution:** Unshallow first if possible:
```bash
git fetch --unshallow
```

## Pack Files

After `git gc`, objects are consolidated into pack files (`.git/objects/pack/`). Pack files use zlib compression and delta encoding.

**Critical**: Raw `grep` on `.git/objects/pack/*.pack` will NOT find secrets inside pack files because the content is compressed. This is a common misconception.

**Reliable methods**:
- `git rev-list --all --objects` + `git cat-file -p` for reachable objects (decompresses before searching)
- `git fsck --unreachable` + `git cat-file -p` for unreachable objects
- `git verify-pack -v .git/objects/pack/*.idx` to enumerate all objects in a pack, then `git cat-file -p` each

The raw filesystem grep is only useful for finding secrets in:
- Loose objects (`.git/objects/XX/YYYY...` files)
- Config files (`.git/config`)
- Ref files (`.git/refs/...`)
- Hook scripts
- Other plaintext files in `.git/`

## Bare Repositories

Bare repos have no working tree. All content is in the object database. Adjust file-existence checks accordingly — skip working tree verification.

## History Rewriting with git filter-repo

When a secret was committed (reachable history), you must rewrite history:

```bash
# Install git-filter-repo if needed
pip install git-filter-repo

# Remove specific blobs
git filter-repo --strip-blobs-with-ids blob_ids.txt

# Or remove by path
git filter-repo --path <path-to-secret-file> --invert-paths

# Or replace content
git filter-repo --replace-text expressions.txt
```

**Warning:** This changes commit SHAs. All downstream clones must re-clone.
