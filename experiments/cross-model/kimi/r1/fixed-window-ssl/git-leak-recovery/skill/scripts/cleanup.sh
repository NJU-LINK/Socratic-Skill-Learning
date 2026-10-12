#!/bin/bash
# Phase 3: Cleanup - Remove secret from all Git storage (tainted-only)
#
# Environment:
#   REPO - Path to git repository (default: /app/repo)
#   PATTERN - Regex pattern to search for (default: 'secret\[[^]]*\]')
#
# This script cleans ONLY objects/locations proven to contain the secret.
# Review survey.sh output first to understand what will be affected.

set -e

REPO="${REPO:-/app/repo}"
PATTERN="${PATTERN:-secret\[[^]]*\]}"

cd "$REPO"

echo "Taking pre-cleanup snapshot..."
mkdir -p /tmp/git-cleanup-snapshot
git for-each-ref > /tmp/git-cleanup-snapshot/before_refs.txt
git log --oneline --all > /tmp/git-cleanup-snapshot/before_log.txt
ls -la > /tmp/git-cleanup-snapshot/before_ls.txt

echo ""
echo "Cleanup Phase 1: Drop tainted stashes only..."
# Stash is a 2-3 commit graph: worktree (sha), index (^2), optionally untracked (^3)
# For commits, use git grep to search trees; for blobs/tags, use cat-file -p
# Must check for ^3 existence before using it, and drop by index in descending order

# Collect all tainted stash indices first
tainted_indices=""
while IFS= read -r line; do
    [ -z "$line" ] && continue
    sha=$(echo "$line" | awk '{print $1}')
    idx=$(echo "$line" | awk '{print $2}')
    
    # Build rev list conditionally (stash may not have ^3)
    revs="$sha $sha^2"
    if git rev-parse --verify -q "$sha^3" >/dev/null 2>&1; then
        revs="$revs $sha^3"
    fi
    
    # Check if secret is in the stash tree(s)
    if git grep -lE "$PATTERN" $revs 2>/dev/null | grep -q .; then
        # Extract numeric index (stash@{N} -> N)
        num=$(echo "$idx" | sed 's/stash@{//;s/}//')
        tainted_indices="$tainted_indices $num"
    fi
done < <(git stash list --format='%H %gd' 2>/dev/null || true)

# Drop in descending order by index to avoid renumbering issues
if [ -n "$tainted_indices" ]; then
    echo "$tainted_indices" | tr ' ' '\n' | grep -v '^$' | sort -rn | while read -r n; do
        echo "  Dropping tainted stash: stash@{$n}"
        git stash drop "stash@{$n}" || true
    done
fi

echo ""
echo "Cleanup Phase 2: Remove tainted refs/tags (annotated tags and branches with tainted history)..."
# Check branches and lightweight tags (secrets anywhere in reachable history)
git for-each-ref --format='%(refname)' refs/heads refs/tags 2>/dev/null | while read -r ref; do
    # Get the object the ref points to
    target=$(git rev-parse "$ref" 2>/dev/null || true)
    [ -z "$target" ] && continue
    
    obj_type=$(git cat-file -t "$target" 2>/dev/null || true)
    tainted=""
    
    if [ "$obj_type" = "commit" ]; then
        # Branch or lightweight tag: check entire reachable history
        # Lightweight tags have no object - taint lives in reachable history like branches
        # When history is rewritten, tags must follow: git filter-branch --tag-name-filter cat
        if git log --all-match --grep="secret\[" -i "$ref" -- 2>/dev/null | grep -q .; then
            tainted="1"
        elif git log -S'secret[' "$ref" -- 2>/dev/null | grep -q .; then
            tainted="1"
        elif git grep -lE "$PATTERN" $(git rev-list "$ref" 2>/dev/null | head -1000) 2>/dev/null | grep -q .; then
            # Check up to 1000 commits back
            tainted="1"
        fi
        
        if [ -n "$tainted" ]; then
            echo "  WARNING: Tainted history found in $ref"
            echo "    This ref has secret in reachable history and needs rewrite (not auto-deleted)."
            echo "    Use: git filter-repo or git filter-branch --force --index-filter '...' --tag-name-filter cat"
            echo "    Then: rm -rf .git/refs/original/; git for-each-ref --format='%(refname)' | grep -v '^refs/stash$' | xargs -r git reflog expire --expire=now; git gc --prune=now"
        fi
    elif [ "$obj_type" = "tag" ]; then
        # Annotated tag: check tag message AND tagged object's full history
        if git cat-file -p "$target" | grep -oE "$PATTERN" > /dev/null; then
            tainted="1"
        fi
        # Check what the tag points to - check full history, not just tip
        tagged_obj=$(git rev-parse "$ref^{commit}" 2>/dev/null || git rev-parse "$ref^{tree}" 2>/dev/null || true)
        if [ -n "$tagged_obj" ]; then
            # Check full reachable history from the tagged commit
            if git log --all-match --grep="secret\[" -i "$tagged_obj" -- 2>/dev/null | grep -q .; then
                tainted="1"
            elif git log -S'secret[' "$tagged_obj" -- 2>/dev/null | grep -q .; then
                tainted="1"
            elif git grep -lE "$PATTERN" $(git rev-list "$tagged_obj" 2>/dev/null | head -1000) 2>/dev/null | grep -q .; then
                tainted="1"
            fi
        fi
        
        if [ -n "$tainted" ]; then
            echo "  Removing tainted annotated tag: $ref"
            git update-ref -d "$ref" || true
        fi
    fi
done

echo ""
echo "Cleanup Phase 3: Remove tainted replace refs only..."
for sha in $(git replace -l 2>/dev/null || true); do
    replace_obj=$(git rev-parse "refs/replace/$sha" 2>/dev/null || true)
    if [ -n "$replace_obj" ]; then
        obj_type=$(git cat-file -t "$replace_obj" 2>/dev/null || true)
        tainted=""
        if [ "$obj_type" = "blob" ]; then
            # Blob: check content directly
            if git cat-file -p "$replace_obj" | grep -oE "$PATTERN" > /dev/null; then
                tainted="1"
            fi
        elif [ "$obj_type" = "commit" ]; then
            # Commit: grep the tree
            if git grep -lE "$PATTERN" "$replace_obj" 2>/dev/null | grep -q .; then
                tainted="1"
            fi
        elif [ "$obj_type" = "tag" ]; then
            # Tag: check tag message (cat-file) AND pointed-to object (grep tree)
            if git cat-file -p "$replace_obj" | grep -oE "$PATTERN" > /dev/null; then
                tainted="1"
            else
                # Check the pointed-to commit/tree
                target=$(git rev-parse "$replace_obj^{commit}" 2>/dev/null || git rev-parse "$replace_obj^{tree}" 2>/dev/null || true)
                if [ -n "$target" ] && git grep -lE "$PATTERN" "$target" 2>/dev/null | grep -q .; then
                    tainted="1"
                fi
            fi
        fi
        if [ -n "$tainted" ]; then
            echo "  Removing tainted replace ref: $sha"
            git replace -d "$sha" || true
        fi
    fi
done

echo ""
echo "Cleanup Phase 4: Expiring reflogs (preserving stash reflog for untainted stashes)..."
# Expire every reflog EXCEPT refs/stash — the stash list IS the reflog of refs/stash.
# Using --all would destroy surviving untainted stashes.
git for-each-ref --format='%(refname)' 2>/dev/null | grep -v '^refs/stash$' \
  | while read -r ref; do
      git reflog expire --expire=now "$ref" 2>/dev/null || true
    done
# HEAD's reflog isn't in for-each-ref, expire it separately
git reflog expire --expire=now HEAD 2>/dev/null || true

echo ""
echo "Cleanup Phase 5: Garbage collecting..."
git gc --prune=now

echo ""
echo "Cleanup Phase 6: Recursing into submodules..."
# Iterate all submodule gitdirs (including uninitialized)
for gitdir in .git/modules/*/; do
    [ -d "$gitdir" ] || continue
    name=$(basename "$gitdir")
    echo "  Checking submodule: $name"
    
    # Check stashes in submodule (handle ^3 conditionally, drop in descending order)
    tainted_sub=""
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        sha=$(echo "$line" | awk '{print $1}')
        idx=$(echo "$line" | awk '{print $2}')
        revs="$sha $sha^2"
        if GIT_DIR="$gitdir" git rev-parse --verify -q "$sha^3" >/dev/null 2>&1; then
            revs="$revs $sha^3"
        fi
        if GIT_DIR="$gitdir" git grep -lE "$PATTERN" $revs 2>/dev/null | grep -q .; then
            num=$(echo "$idx" | sed 's/stash@{//;s/}//')
            tainted_sub="$tainted_sub $num"
        fi
    done < <(GIT_DIR="$gitdir" git stash list --format='%H %gd' 2>/dev/null || true)
    
    if [ -n "$tainted_sub" ]; then
        echo "$tainted_sub" | tr ' ' '\n' | grep -v '^$' | sort -rn | while read -r n; do
            echo "    Dropping tainted stash: stash@{$n}"
            GIT_DIR="$gitdir" git stash drop "stash@{$n}" || true
        done
    fi
    
    # Expire reflogs (preserve stash reflog) and gc
    GIT_DIR="$gitdir" git for-each-ref --format='%(refname)' 2>/dev/null | grep -v '^refs/stash$' \
      | while read -r ref; do
          GIT_DIR="$gitdir" git reflog expire --expire=now "$ref" 2>/dev/null || true
        done
    GIT_DIR="$gitdir" git reflog expire --expire=now HEAD 2>/dev/null || true
    GIT_DIR="$gitdir" git gc --prune=now 2>/dev/null || true
done

echo ""
echo "Cleanup complete."
echo "Pre-cleanup snapshot saved in /tmp/git-cleanup-snapshot/"
echo "Use verify.sh to confirm both cleanup and preservation."
