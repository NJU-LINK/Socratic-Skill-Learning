#!/usr/bin/env bash
# recover_and_clean.sh — Git Leak Recovery: search-first, then clean
#
# Usage: recover_and_clean.sh <repo_path> <output_file> [secret_pattern]
#
# Arguments:
#   repo_path       Path to the git repository (e.g., /app/repo)
#   output_file     Where to write the recovered secret (e.g., /app/secret.txt)
#   secret_pattern  Optional regex for the secret (default: 'secret\[[^]]*\]')
#
# Protocol:
#   1. Search all locations in order, collecting candidates BEFORE any cleanup
#   2. Write the first found secret to output_file
#   3. Clean up every location where the secret was found
#   4. Verify the secret is gone from all locations
#   5. Verify legitimate content is preserved

set -euo pipefail

REPO="${1:?Usage: $0 <repo_path> <output_file> [secret_pattern]}"
OUTPUT="${2:?Usage: $0 <repo_path> <output_file> [secret_pattern]}"
PATTERN="${3:-secret\[[^]]*\]}"

cd "$REPO"

FOUND_SECRET=""
declare -a FOUND_LOCATIONS=()

log() { echo "[git-leak-recovery] $*"; }

# Helper: check content for the secret pattern, return match or empty
extract_secret() {
    echo "$1" | grep -oE "$PATTERN" | head -1 || true
}

# ─── PHASE 1: SEARCH (before any cleanup) ───────────────────────────────────

# 1. Reachable history — search all blobs reachable from any ref
log "Searching reachable history..."
while IFS=' ' read -r sha rest; do
    [ -z "$sha" ] && continue
    type=$(git cat-file -t "$sha" 2>/dev/null || true)
    if [ "$type" = "blob" ]; then
        content=$(git cat-file -p "$sha" 2>/dev/null || true)
        match=$(extract_secret "$content")
        if [ -n "$match" ]; then
            [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
            FOUND_LOCATIONS+=("reachable_history")
            log "Found secret in reachable history: $FOUND_SECRET"
        fi
    fi
done < <(git rev-list --objects --all 2>/dev/null || true)

# 2. Stashes
log "Searching stashes..."
STASH_COUNT=$(git stash list 2>/dev/null | wc -l || echo 0)
if [ "$STASH_COUNT" -gt 0 ]; then
    for i in $(seq 0 $((STASH_COUNT - 1))); do
        stash_content=$(git stash show -p "stash@{$i}" 2>/dev/null || true)
        match=$(extract_secret "$stash_content")
        if [ -n "$match" ]; then
            [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
            FOUND_LOCATIONS+=("stash@$i")
            log "Found secret in stash@{$i}: $match"
        fi
    done
fi

# 3. Reflogs — inspect commits referenced only by reflogs
log "Searching reflogs..."
while read -r sha; do
    [ -z "$sha" ] && continue
    while IFS=' ' read -r obj rest; do
        [ -z "$obj" ] && continue
        obj_type=$(git cat-file -t "$obj" 2>/dev/null || true)
        if [ "$obj_type" = "blob" ]; then
            content=$(git cat-file -p "$obj" 2>/dev/null || true)
            match=$(extract_secret "$content")
            if [ -n "$match" ]; then
                [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
                FOUND_LOCATIONS+=("reflog:$sha")
                log "Found secret in reflog entry $sha: $match"
                break 2
            fi
        fi
    done < <(git rev-list --objects "$sha" 2>/dev/null || true)
done < <(git reflog --all --format='%H' 2>/dev/null || true)

# 4. Unreachable/dangling objects (git fsck)
log "Searching unreachable objects..."
while read -r line; do
    [[ "$line" =~ ^(unreachable|dangling)\ (blob|commit|tree)\ ([a-f0-9]+)$ ]] || continue
    obj_type="${BASH_REMATCH[2]}"
    sha="${BASH_REMATCH[3]}"
    case "$obj_type" in
        blob)
            content=$(git cat-file -p "$sha" 2>/dev/null || true)
            match=$(extract_secret "$content")
            if [ -n "$match" ]; then
                [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
                FOUND_LOCATIONS+=("unreachable_blob:$sha")
                log "Found secret in unreachable blob $sha: $match"
            fi
            ;;
        commit)
            while IFS=' ' read -r obj rest; do
                [ -z "$obj" ] && continue
                ot=$(git cat-file -t "$obj" 2>/dev/null || true)
                if [ "$ot" = "blob" ]; then
                    content=$(git cat-file -p "$obj" 2>/dev/null || true)
                    match=$(extract_secret "$content")
                    if [ -n "$match" ]; then
                        [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
                        FOUND_LOCATIONS+=("unreachable_commit:$sha")
                        log "Found secret in unreachable commit $sha: $match"
                        break
                    fi
                fi
            done < <(git rev-list --objects "$sha" 2>/dev/null || true)
            ;;
        tree)
            while IFS=$'\t' read -r mode_type_hash path; do
                blob_sha=$(echo "$mode_type_hash" | awk '{print $3}')
                [ -z "$blob_sha" ] && continue
                content=$(git cat-file -p "$blob_sha" 2>/dev/null || true)
                match=$(extract_secret "$content")
                if [ -n "$match" ]; then
                    [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
                    FOUND_LOCATIONS+=("unreachable_tree:$sha")
                    log "Found secret in unreachable tree $sha: $match"
                    break
                fi
            done < <(git ls-tree -r "$sha" 2>/dev/null || true)
            ;;
    esac
done < <(git fsck --unreachable --no-reflogs --dangling 2>&1 || true)

# 5. Replace refs
log "Searching replace refs..."
while read -r original replacement; do
    [ -z "$original" ] && continue
    content=$(git cat-file -p "$original" 2>/dev/null || true)
    match=$(extract_secret "$content")
    if [ -n "$match" ]; then
        [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
        FOUND_LOCATIONS+=("replace_ref:$original")
        log "Found secret in replace ref original $original: $match"
    fi
done < <(git replace -l 2>/dev/null || true)

# 6. All refs (backup refs, notes, etc.)
log "Searching all refs..."
while read -r refname refsha; do
    [ -z "$refname" ] && continue
    type=$(git cat-file -t "$refsha" 2>/dev/null || true)
    if [ "$type" = "commit" ]; then
        while IFS=' ' read -r obj rest; do
            [ -z "$obj" ] && continue
            ot=$(git cat-file -t "$obj" 2>/dev/null || true)
            if [ "$ot" = "blob" ]; then
                content=$(git cat-file -p "$obj" 2>/dev/null || true)
                match=$(extract_secret "$content")
                if [ -n "$match" ]; then
                    [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
                    FOUND_LOCATIONS+=("ref:$refname")
                    log "Found secret in ref $refname: $match"
                    break
                fi
            fi
        done < <(git rev-list --objects "$refsha" 2>/dev/null || true)
    elif [ "$type" = "blob" ]; then
        content=$(git cat-file -p "$refsha" 2>/dev/null || true)
        match=$(extract_secret "$content")
        if [ -n "$match" ]; then
            [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
            FOUND_LOCATIONS+=("ref:$refname")
            log "Found secret in ref $refname (blob): $match"
        fi
    fi
done < <(git for-each-ref --format='%(refname) %(objectname)' 2>/dev/null || true)

# 7. Tags (annotated tag objects)
log "Searching tags..."
while read -r tag; do
    [ -z "$tag" ] && continue
    tag_sha=$(git rev-parse "refs/tags/$tag" 2>/dev/null || true)
    tag_type=$(git cat-file -t "$tag_sha" 2>/dev/null || true)
    if [ "$tag_type" = "tag" ]; then
        tag_content=$(git cat-file -p "$tag_sha" 2>/dev/null || true)
        match=$(extract_secret "$tag_content")
        if [ -n "$match" ]; then
            [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
            FOUND_LOCATIONS+=("tag:$tag")
            log "Found secret in annotated tag $tag: $match"
        fi
    fi
done < <(git tag -l 2>/dev/null || true)

# 8. Submodule object databases
log "Searching submodule object databases..."
if [ -f .gitmodules ]; then
    while read -r mode sha path; do
        [ -z "$path" ] && continue
        for candidate in "$path/.git" ".git/modules/$path"; do
            if [ -d "$candidate/objects" ]; then
                while read -r fsck_line; do
                    [[ "$fsck_line" =~ ^(unreachable|dangling)\ blob\ ([a-f0-9]+)$ ]] || continue
                    bsha="${BASH_REMATCH[2]}"
                    content=$(GIT_DIR="$candidate" git cat-file -p "$bsha" 2>/dev/null || true)
                    match=$(extract_secret "$content")
                    if [ -n "$match" ]; then
                        [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
                        FOUND_LOCATIONS+=("submodule:$path")
                        log "Found secret in submodule $path: $match"
                    fi
                done < <(GIT_DIR="$candidate" git fsck --unreachable --no-reflogs 2>&1 || true)
            fi
        done
    done < <(git submodule--helper list 2>/dev/null || true)
fi

# Safety net: brute-force scan ALL objects in ODB (loose + packed)
log "Brute-force scanning all objects in object database..."
while read -r sha; do
    [ -z "$sha" ] && continue
    type=$(git cat-file -t "$sha" 2>/dev/null || true)
    if [ "$type" = "blob" ]; then
        content=$(git cat-file -p "$sha" 2>/dev/null || true)
        match=$(extract_secret "$content")
        if [ -n "$match" ]; then
            [ -z "$FOUND_SECRET" ] && FOUND_SECRET="$match"
            FOUND_LOCATIONS+=("raw_object:$sha")
            log "Found secret in raw object $sha: $match"
        fi
    fi
done < <({
    find .git/objects -type f ! -path '*/pack/*' ! -path '*/info/*' 2>/dev/null | \
        sed 's|.git/objects/||;s|/||'
    for pack in .git/objects/pack/*.idx; do
        [ -f "$pack" ] || continue
        git verify-pack -v "$pack" 2>/dev/null | grep '^[a-f0-9]\{40\} blob' | awk '{print $1}'
    done
})

# ─── PHASE 2: WRITE RECOVERED SECRET ────────────────────────────────────────

if [ -z "$FOUND_SECRET" ]; then
    log "ERROR: No secret matching pattern '$PATTERN' found anywhere in the repository."
    exit 1
fi

echo -n "$FOUND_SECRET" > "$OUTPUT"
log "Recovered secret written to $OUTPUT: $FOUND_SECRET"
log "Found in locations: ${FOUND_LOCATIONS[*]}"

# ─── PHASE 3: CLEANUP ───────────────────────────────────────────────────────

log "Starting cleanup..."

# 3a. Remove tainted stashes
for loc in "${FOUND_LOCATIONS[@]}"; do
    if [[ "$loc" == stash@* ]]; then
        idx=$(echo "$loc" | sed 's/stash@{//;s/}//')
        log "Dropping tainted stash stash@{$idx}..."
        git stash drop "stash@{$idx}" 2>/dev/null || true
    fi
done

# 3b. Remove replace refs
for loc in "${FOUND_LOCATIONS[@]}"; do
    if [[ "$loc" == replace_ref:* ]]; then
        orig=$(echo "$loc" | sed 's/replace_ref://')
        log "Removing replace ref for $orig..."
        git replace -d "$orig" 2>/dev/null || true
    fi
done

# 3c. Remove tainted tags
for loc in "${FOUND_LOCATIONS[@]}"; do
    if [[ "$loc" == tag:* ]]; then
        tagname=$(echo "$loc" | sed 's/tag://')
        log "Deleting tainted tag $tagname..."
        git tag -d "$tagname" 2>/dev/null || true
    fi
done

# 3d. Remove tainted backup/notes refs
for loc in "${FOUND_LOCATIONS[@]}"; do
    if [[ "$loc" == ref:refs/original/* ]] || [[ "$loc" == ref:refs/notes/* ]]; then
        refname=$(echo "$loc" | sed 's/ref://')
        log "Deleting tainted ref $refname..."
        git update-ref -d "$refname" 2>/dev/null || true
    fi
done

# 3e. If secret is in reachable history, rewrite history
NEEDS_REWRITE=false
for loc in "${FOUND_LOCATIONS[@]}"; do
    if [[ "$loc" == "reachable_history" ]]; then
        NEEDS_REWRITE=true
        break
    fi
done

if $NEEDS_REWRITE; then
    log "Secret found in reachable history — rewriting..."
    # Find tainted files by searching all reachable blobs for the pattern
    TAINTED_FILES=""
    while IFS=' ' read -r sha rest; do
        [ -z "$sha" ] && continue
        type=$(git cat-file -t "$sha" 2>/dev/null || true)
        if [ "$type" = "blob" ]; then
            content=$(git cat-file -p "$sha" 2>/dev/null || true)
            match=$(extract_secret "$content")
            if [ -n "$match" ] && [ -n "$rest" ]; then
                TAINTED_FILES="$TAINTED_FILES $rest"
            fi
        fi
    done < <(git rev-list --objects --all 2>/dev/null || true)

    if [ -n "$TAINTED_FILES" ]; then
        TAINTED_FILES=$(echo "$TAINTED_FILES" | tr ' ' '\n' | sort -u | tr '\n' ' ')
        for tf in $TAINTED_FILES; do
            log "Rewriting history to remove tainted file: $tf"
        done
        FILTER_CMD=""
        for tf in $TAINTED_FILES; do
            FILTER_CMD="${FILTER_CMD}rm -f \"$tf\"; "
        done
        git filter-branch --force --tree-filter "$FILTER_CMD" --prune-empty -- --all 2>/dev/null || true
        # Remove backup refs
        git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null | while read -r ref; do
            git update-ref -d "$ref" 2>/dev/null || true
        done
    fi
fi

# 3f. Expire all reflogs
log "Expiring all reflogs..."
git reflog expire --expire=now --all 2>/dev/null || true

# 3g. Prune unreachable objects
log "Pruning unreachable objects..."
git gc --prune=now --aggressive 2>/dev/null || true

# 3h. Repack
log "Repacking..."
git repack -a -d 2>/dev/null || true

# 3i. Clean submodule ODBs
if [ -f .gitmodules ]; then
    while read -r mode sha path; do
        [ -z "$path" ] && continue
        for candidate in "$path/.git" ".git/modules/$path"; do
            if [ -d "$candidate" ]; then
                log "Cleaning submodule $path..."
                GIT_DIR="$candidate" git reflog expire --expire=now --all 2>/dev/null || true
                GIT_DIR="$candidate" git gc --prune=now --aggressive 2>/dev/null || true
            fi
        done
    done < <(git submodule--helper list 2>/dev/null || true)
fi

# ─── PHASE 4: VERIFICATION ──────────────────────────────────────────────────

log "Verifying cleanup..."
VERIFY_FAILED=false

# Re-scan all blobs in the ODB
while read -r sha; do
    [ -z "$sha" ] && continue
    type=$(git cat-file -t "$sha" 2>/dev/null || true)
    if [ "$type" = "blob" ]; then
        content=$(git cat-file -p "$sha" 2>/dev/null || true)
        match=$(extract_secret "$content")
        if [ -n "$match" ]; then
            log "VERIFICATION FAILED: Secret still in blob $sha"
            VERIFY_FAILED=true
        fi
    fi
done < <({
    find .git/objects -type f ! -path '*/pack/*' ! -path '*/info/*' 2>/dev/null | \
        sed 's|.git/objects/||;s|/||'
    for pack in .git/objects/pack/*.idx; do
        [ -f "$pack" ] || continue
        git verify-pack -v "$pack" 2>/dev/null | grep '^[a-f0-9]\{40\} blob' | awk '{print $1}'
    done
})

# Check fsck
while read -r line; do
    [[ "$line" =~ ^(unreachable|dangling)\ blob\ ([a-f0-9]+)$ ]] || continue
    sha="${BASH_REMATCH[2]}"
    content=$(git cat-file -p "$sha" 2>/dev/null || true)
    match=$(extract_secret "$content")
    if [ -n "$match" ]; then
        log "VERIFICATION FAILED: Secret still in unreachable blob $sha"
        VERIFY_FAILED=true
    fi
done < <(git fsck --unreachable --no-reflogs --dangling 2>&1 || true)

# Check stashes
STASH_CHECK=$(git stash list 2>/dev/null || true)
if [ -n "$STASH_CHECK" ]; then
    count=$(echo "$STASH_CHECK" | wc -l)
    for i in $(seq 0 $((count - 1))); do
        stash_content=$(git stash show -p "stash@{$i}" 2>/dev/null || true)
        match=$(extract_secret "$stash_content")
        if [ -n "$match" ]; then
            log "VERIFICATION FAILED: Secret still in stash@{$i}"
            VERIFY_FAILED=true
        fi
    done
fi

if $VERIFY_FAILED; then
    log "WARNING: Verification found remaining instances. Manual intervention may be needed."
    exit 2
else
    log "Verification passed: secret is no longer present in any object."
fi

# Verify legitimate content preserved
BRANCHES=$(git branch --format='%(refname:short)' 2>/dev/null | wc -l)
COMMITS=$(git rev-list --all --count 2>/dev/null || echo 0)
log "Repository has $BRANCHES branch(es) and $COMMITS commit(s)."
log "Cleanup complete."

exit 0
