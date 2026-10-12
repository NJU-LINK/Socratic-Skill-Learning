#!/bin/bash
# Git Secret Recovery and Cleanup Script
# Usage: recover-secret.sh [repo_path] [output_file]

set -e

REPO_PATH="${1:-/app/repo}"
OUTPUT_FILE="${2:-/app/secret.txt}"
SECRET_PATTERN="secret\["

if [ ! -d "$REPO_PATH/.git" ]; then
    echo "ERROR: Not a git repository: $REPO_PATH"
    exit 1
fi

cd "$REPO_PATH"

echo "=== Phase 1: Discovery ==="

found_log=$(mktemp)
secret_value=""

extract_secret() {
    echo "$1" | grep -oE 'secret\[[^]]*\]' | head -1
}

# 1. Worktree
echo "Checking worktree..."
content=$(grep -rh "$SECRET_PATTERN" . --include="*" 2>/dev/null | grep -v ".git/" | head -1 || true)
if [ -n "$content" ]; then
    echo "worktree" >> "$found_log"
    secret_value=$(extract_secret "$content")
fi

# 2. Index
echo "Checking index..."
git ls-files --stage 2>/dev/null | while read mode hash stage path; do
    [ -z "$hash" ] && continue
    if git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
        echo "index:$path" >> "$found_log"
    fi
done

# 3. Reachable commits
echo "Checking reachable commits..."
for commit in $(git rev-list --all 2>/dev/null); do
    if git grep -q "$SECRET_PATTERN" "$commit" -- 2>/dev/null; then
        echo "reachable:$commit" >> "$found_log"
    fi
done

# 4. Unreachable objects
echo "Checking unreachable objects..."
git fsck --unreachable --no-reflogs 2>&1 | while IFS= read -r line; do
    if [[ "$line" =~ ^unreachable.*\ ([a-f0-9]+) ]]; then
        hash="${BASH_REMATCH[1]}"
        if git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
            echo "unreachable:$hash" >> "$found_log"
        fi
    fi
done

# 5. Tags
echo "Checking annotated tags..."
for tag in $(git tag -l 2>/dev/null); do
    content=$(git cat-file -p "$tag" 2>/dev/null || true)
    if echo "$content" | grep -q "$SECRET_PATTERN"; then
        echo "tag:$tag" >> "$found_log"
    fi
done

# Analyze results
if [ -s "$found_log" ]; then
    while IFS=: read -r type value; do
        case "$type" in
            worktree) echo "Found in worktree" ;;
            index) echo "Found in index: $value" ;;
            reachable) echo "Found in reachable commit: $value" ;;
            unreachable) echo "Found in unreachable: $value" ;;
            tag) echo "Found in annotated tag: $value" ;;
        esac
    done < "$found_log"
fi

# Extract secret value from various sources
if [ -z "$secret_value" ]; then
    hash=$(git fsck --unreachable --no-reflogs 2>&1 | awk '/unreachable blob/ {print $3; exit}')
    if [ -n "$hash" ]; then
        content=$(git cat-file -p "$hash" 2>/dev/null || true)
        secret_value=$(extract_secret "$content")
    fi
fi

if [ -z "$secret_value" ]; then
    for tag in $(git tag -l 2>/dev/null); do
        content=$(git cat-file -p "$tag" 2>/dev/null || true)
        if echo "$content" | grep -q "$SECRET_PATTERN"; then
            secret_value=$(extract_secret "$content")
            break
        fi
    done
fi

if [ -z "$secret_value" ]; then
    git ls-files --stage 2>/dev/null | while read mode hash stage path; do
        [ -z "$hash" ] && continue
        if git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
            content=$(git cat-file -p "$hash" 2>/dev/null)
            secret_value=$(extract_secret "$content")
            break
        fi
    done
fi

if [ -z "$secret_value" ]; then
    for commit in $(git rev-list --all 2>/dev/null); do
        if git grep -q "$SECRET_PATTERN" "$commit" -- 2>/dev/null; then
            match=$(git grep "$SECRET_PATTERN" "$commit" -- 2>/dev/null | head -1)
            secret_value=$(extract_secret "$match")
            break
        fi
    done
fi

if [ -z "$secret_value" ]; then
    rm -f "$found_log"
    echo "ERROR: Secret not found"
    exit 1
fi

echo ""
echo "Secret: $secret_value"

# Phase 2: Extraction
echo ""
echo "=== Phase 2: Extraction ==="
echo "$secret_value" > "$OUTPUT_FILE"
echo "Written to $OUTPUT_FILE"

# Phase 3: Cleanup
echo ""
echo "=== Phase 3: Cleanup ==="

# Determine what needs cleanup
grep -q "^index:" "$found_log" 2>/dev/null && has_index=1 || has_index=0
grep -q "^reachable:" "$found_log" 2>/dev/null && has_reachable=1 || has_reachable=0
grep -q "^tag:" "$found_log" 2>/dev/null && has_tag=1 || has_tag=0
rm -f "$found_log"

# Remove from index
if [ "$has_index" -eq 1 ]; then
    echo "Unstaging files..."
    git ls-files --stage | while read mode hash stage path; do
        [ -n "$hash" ] || continue
        if git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
            git rm --cached "$path" 2>/dev/null || true
        fi
    done
fi

# Remove tainted tags
if [ "$has_tag" -eq 1 ]; then
    echo "Removing tainted tags..."
    for tag in $(git tag -l); do
        if git cat-file -p "$tag" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
            git tag -d "$tag" 2>/dev/null || true
        fi
    done
fi

# Rewrite reachable history
if [ "$has_reachable" -eq 1 ]; then
    echo "Rewriting reachable history..."
    if command -v git-filter-repo &>/dev/null; then
        git filter-repo --replace-text <(echo "regex:${SECRET_PATTERN}[^]]*\]==>***REMOVED***") --force
    else
        git filter-branch --index-filter '
            git grep -l -z "secret\[" $GIT_COMMIT 2>/dev/null | xargs -0 git rm --cached --ignore-unmatch 2>/dev/null || true
        ' --tag-name-filter cat -- --all 2>/dev/null || true
        rm -rf .git/refs/original/
    fi
fi

# Remove pins
git reflog expire --expire=now --all
git stash clear 2>/dev/null || true
for ref in $(git replace -l 2>/dev/null); do
    git replace --delete "$ref" 2>/dev/null || true
done

# Prune
git prune --expire=now
git gc --prune=now --aggressive 2>/dev/null || true

# Phase 4: Verification
echo ""
echo "=== Phase 4: Verification ==="

verify_failed=0

# Check index
if git ls-files --stage 2>/dev/null | while read mode hash stage path; do
    [ -n "$hash" ] || continue
    if git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
        echo "FAIL: Secret in index: $path"
        exit 1
    fi
done; then : ; else verify_failed=1; fi

# Check reachable commits
for commit in $(git rev-list --all 2>/dev/null); do
    if git grep -q "$SECRET_PATTERN" "$commit" -- 2>/dev/null; then
        echo "FAIL: Secret in commit $commit"
        verify_failed=1
    fi
done

# Check unreachable
git fsck --unreachable --no-reflogs 2>&1 | while IFS= read -r line; do
    if [[ "$line" =~ ^unreachable.*\ ([a-f0-9]+) ]]; then
        hash="${BASH_REMATCH[1]}"
        if git cat-file -p "$hash" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
            echo "FAIL: Secret in unreachable $hash"
            exit 1
        fi
    fi
done || verify_failed=1

# Check tags
for tag in $(git tag -l 2>/dev/null); do
    if git cat-file -p "$tag" 2>/dev/null | grep -q "$SECRET_PATTERN"; then
        echo "FAIL: Secret in tag $tag"
        verify_failed=1
    fi
done

if [ "$verify_failed" -eq 0 ]; then
    echo "SUCCESS: Secret removed"
else
    echo "FAIL: verification failed"
    exit 1
fi

echo ""
echo "Done. Secret recovered to $OUTPUT_FILE"
