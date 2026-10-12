#!/bin/bash
#
# Git Secret Recovery and Cleanup Script
#

set -euo pipefail

REPO_PATH="${1:-}"
OUTPUT_FILE="${2:-}"
PATTERN="${3:-secret\[}"

if [[ -z "$REPO_PATH" || -z "$OUTPUT_FILE" ]]; then
    echo "Usage: $0 <repo-path> <output-file> [secret-pattern]"
    exit 1
fi

if ! REPO_GIT_DIR=$(git -C "$REPO_PATH" rev-parse --git-dir 2>/dev/null); then
    echo "Error: $REPO_PATH is not a git repository"
    exit 1
fi

REPO_PATH=$(cd "$REPO_PATH" && pwd)
REPO_GIT_DIR=$(cd "$REPO_PATH" && git rev-parse --git-dir)

log() { echo "[INFO] $1"; }
warn() { echo "[WARN] $1"; }
error() { echo "[ERROR] $1"; }

# Phase A: Snapshot
SNAP_DIR=$(mktemp -d)
trap 'rm -rf "$SNAP_DIR"' EXIT

log "Phase A: Snapshotting state..."
git -C "$REPO_PATH" log --all --format='%H %s' > "$SNAP_DIR/commits.txt" 2>/dev/null || true
git -C "$REPO_PATH" tag -l > "$SNAP_DIR/tags.txt" 2>/dev/null || true
git -C "$REPO_PATH" stash list > "$SNAP_DIR/stashes.txt" 2>/dev/null || true
git -C "$REPO_PATH" ls-files -s > "$SNAP_DIR/index.txt" 2>/dev/null || true

# Phase B: Discover
cd "$REPO_PATH"
log "Phase B: Discovering secret..."

TAINTED_FILE="$SNAP_DIR/tainted.txt"
> "$TAINTED_FILE"

git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' 2>/dev/null | \
while IFS= read -r line; do
    hash=$(echo "$line" | awk '{print $1}')
    type=$(echo "$line" | awk '{print $2}')
    if [[ -n "$hash" && -n "$type" ]]; then
        if git cat-file "$type" "$hash" 2>/dev/null | grep -q "$PATTERN" 2>/dev/null; then
            echo "$hash $type" >> "$TAINTED_FILE"
        fi
    fi
done

if [[ ! -s "$TAINTED_FILE" ]]; then
    error "No secret found"
    exit 1
fi

log "Found $(wc -l < "$TAINTED_FILE") tainted object(s)"

TAINTED_HASHES="$SNAP_DIR/tainted_hashes.txt"
cut -d' ' -f1 "$TAINTED_FILE" | sort -u > "$TAINTED_HASHES"

# Recover - first try blobs, then any tainted object
SECRET_FOUND=0
while IFS= read -r line && [[ $SECRET_FOUND -eq 0 ]]; do
    hash=$(echo "$line" | awk '{print $1}')
    type=$(echo "$line" | awk '{print $2}')
    if [[ "$type" == "blob" ]]; then
        git cat-file blob "$hash" > "$OUTPUT_FILE"
        SECRET_FOUND=1
    fi
done < "$TAINTED_FILE"

# If no blob found, extract pattern from first tainted object (commit/tag message)
if [[ $SECRET_FOUND -eq 0 ]]; then
    hash=$(head -1 "$TAINTED_FILE" | awk '{print $1}')
    type=$(head -1 "$TAINTED_FILE" | awk '{print $2}')
    log "Extracting from $type $hash (non-blob)"
    # Extract just the pattern match, not the whole object
    git cat-file -p "$hash" 2>/dev/null | grep -aoE "$PATTERN[^]]*\]" | head -1 > "$OUTPUT_FILE" || {
        error "Could not extract secret from $type"
        exit 1
    }
fi

if [[ ! -s "$OUTPUT_FILE" ]]; then
    error "Secret extraction failed - output file is empty"
    exit 1
fi

log "Secret written to $OUTPUT_FILE"

# Phase C: Cut References
log "Phase C: Cutting references..."

# C1: Handle staged files
log "Checking for staged tainted blobs..."
while IFS= read -r idxline; do
    [[ -z "$idxline" ]] && continue
    read -r mode obj stage path <<< "$idxline"
    if grep -q "^$obj" "$TAINTED_HASHES" 2>/dev/null; then
        log "Removing staged tainted file: $path"
        git rm --cached "$path" 2>/dev/null || true
    fi
done < "$SNAP_DIR/index.txt"

# C2: Handle stashes
STASH_DROP="$SNAP_DIR/stash_drop.txt"
> "$STASH_DROP"
git stash list --format='%H %gd' 2>/dev/null > "$SNAP_DIR/stash_list.txt" || true

while IFS= read -r line; do
    commit=$(echo "$line" | awk '{print $1}')
    stash_ref=$(echo "$line" | awk '{print $2}')
    tainted=$(git rev-list --objects "$commit" 2>/dev/null | cut -d' ' -f1 | grep -Ff "$TAINTED_HASHES" 2>/dev/null | head -1 || true)
    if [[ -n "$tainted" ]]; then
        idx=$(echo "$stash_ref" | sed 's/stash@{//;s/}//')
        echo "$idx $stash_ref" >> "$STASH_DROP"
    fi
done < "$SNAP_DIR/stash_list.txt"

if [[ -s "$STASH_DROP" ]]; then
    sort -rn "$STASH_DROP" | while read -r idx stash_ref; do
        log "Dropping tainted stash: $stash_ref"
        git stash drop "$stash_ref" 2>/dev/null || warn "Failed to drop"
    done
fi

# C3: Replace refs
for ref in $(git replace -l 2>/dev/null); do
    if grep -q "^$ref" "$TAINTED_HASHES" 2>/dev/null; then
        git replace -d "$ref" 2>/dev/null || true
    fi
done

# C4: Backup refs
git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null | while read -r ref; do
    git update-ref -d "$ref" 2>/dev/null || true
done

# C5: Tainted annotated tags
git for-each-ref --format='%(objectname) %(refname)' refs/tags/ 2>/dev/null | while IFS= read -r line; do
    obj=$(echo "$line" | awk '{print $1}')
    ref=$(echo "$line" | awk '{print $2}')
    if grep -q "^$obj" "$TAINTED_HASHES" 2>/dev/null; then
        git tag -d "${ref#refs/tags/}" 2>/dev/null || true
    fi
done

# C6: Reachable history rewrite (for blobs and commit messages)
NEEDS_REWRITE=0
TAINTED_COMMITS="$SNAP_DIR/tainted_commits.txt"
> "$TAINTED_COMMITS"
while IFS= read -r line; do
    hash=$(echo "$line" | awk '{print $1}')
    type=$(echo "$line" | awk '{print $2}')
    if git rev-list --all --objects 2>/dev/null | grep -q "^$hash"; then
        NEEDS_REWRITE=1
        [[ "$type" == "commit" ]] && echo "$hash" >> "$TAINTED_COMMITS"
    fi
done < "$TAINTED_FILE"

if [[ $NEEDS_REWRITE -eq 1 ]]; then
    log "Rewriting reachable history..."
    TAINTED_PATHS="$SNAP_DIR/tainted_paths.txt"
    > "$TAINTED_PATHS"
    while IFS= read -r line; do
        hash=$(echo "$line" | awk '{print $1}')
        type=$(echo "$line" | awk '{print $2}')
        if [[ "$type" == "blob" ]]; then
            git rev-list --all --objects 2>/dev/null | grep "^$hash " | while read -r _ path; do
                [[ -n "$path" ]] && echo "$path"
            done
        fi
    done < "$TAINTED_FILE" | sort -u > "$TAINTED_PATHS"
    
    # Build filter options
    INDEX_FILTER=""
    MSG_FILTER=""
    
    if [[ -s "$TAINTED_PATHS" ]]; then
        FILTER_CMD=""
        while IFS= read -r path; do
            FILTER_CMD="${FILTER_CMD}git rm --cached --ignore-unmatch '$path' || true; "
        done < "$TAINTED_PATHS"
        INDEX_FILTER="$FILTER_CMD"
    fi
    
    if [[ -s "$TAINTED_COMMITS" ]]; then
        # Redact commit messages
        MSG_FILTER="sed 's/$PATTERN[^]]*\]/REDACTED/g'"
    fi
    
    # Run filter-branch with appropriate filters
    if [[ -n "$INDEX_FILTER" && -n "$MSG_FILTER" ]]; then
        git filter-branch --index-filter "$INDEX_FILTER" --msg-filter "$MSG_FILTER" --tag-name-filter cat -- --all 2>/dev/null || warn "filter-branch had nothing to do"
    elif [[ -n "$INDEX_FILTER" ]]; then
        git filter-branch --index-filter "$INDEX_FILTER" --tag-name-filter cat -- --all 2>/dev/null || warn "filter-branch had nothing to do"
    elif [[ -n "$MSG_FILTER" ]]; then
        git filter-branch --msg-filter "$MSG_FILTER" --tag-name-filter cat -- --all 2>/dev/null || warn "filter-branch had nothing to do"
    fi
    
    git for-each-ref --format='%(refname)' refs/original/ 2>/dev/null | while read -r ref; do
        git update-ref -d "$ref" 2>/dev/null || true
    done
fi

# Phase D: Purge (skip refs/stash)
log "Phase D: Purging..."
while IFS= read -r ref; do
    [[ "$ref" == "refs/stash" ]] && continue
    git reflog expire --expire=now --expire-unreachable=now "$ref" 2>/dev/null || true
done < <(git for-each-ref --format='%(refname)'; echo "HEAD")

git gc --prune=now
git prune --expire=now

# Phase E: Verify
log "Phase E: Verification..."
FOUND_ANY=0
while IFS= read -r line; do
    hash=$(echo "$line" | awk '{print $1}')
    type=$(echo "$line" | awk '{print $2}')
    if [[ -n "$hash" && -n "$type" ]]; then
        if git cat-file "$type" "$hash" 2>/dev/null | grep -q "$PATTERN" 2>/dev/null; then
            error "FAIL: Secret still in $hash ($type)"
            FOUND_ANY=1
        fi
    fi
done < <(git cat-file --batch-all-objects --batch-check='%(objectname) %(objecttype)' 2>/dev/null)

[[ $FOUND_ANY -eq 1 ]] && exit 1
log "Verification passed"
rm -rf "$SNAP_DIR"
trap - EXIT
log "Recovery complete"
