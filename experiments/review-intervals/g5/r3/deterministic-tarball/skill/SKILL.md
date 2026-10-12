---
name: deterministic-tarball
description: Build bit-for-bit reproducible release archives with deterministic metadata normalization, exclusion rules, and compression
---

# Deterministic Tarball Packaging

Build reproducible release archives from source trees with metadata normalization, exclusion filtering, and deterministic compression.

## Core Architecture

Use a **staging directory** approach to avoid modifying the source tree:

1. Copy source tree to temporary staging directory (preserve symlinks with `cp -a`)
2. Apply exclusion rules (remove unwanted files/dirs from staging)
3. Normalize permissions and line endings in staging
4. Build tar archive from staging with deterministic flags
5. Compress with zstd
6. Clean up staging directory

## Key Mechanisms

### 1. Exclusion Rule Parsing

Parse `.distignore` (gitignore-style syntax) line-by-line:

```bash
while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    [[ -z "$pattern" || "$pattern" == \#* ]] && continue
    pattern="${pattern%/}"  # Strip trailing /
    
    case "$pattern" in
        \*\*/*)
            # **/dirname — match directory at any depth
            inner="${pattern#\*\*/}"
            find "$STAGING" -depth -name "$inner" -exec rm -rf {} +
            ;;
        \**)
            # Glob pattern like *.tmp — match files at any depth
            find "$STAGING" -name "$pattern" -type f -delete
            ;;
        *)
            # Literal path relative to root
            rm -rf "$STAGING/$pattern"
            ;;
    esac
done < "$SRC/.distignore"
```

**Critical:** The case pattern `\**)` matches single-asterisk globs like `*.tmp`, `*.pyc`. The pattern `\*\*/*` matches double-asterisk directory patterns like `**/__pycache__/`.

### 2. Mode-Based Exclusion

Exclude files with specific permissions (e.g., 0600 for sensitive files):

```bash
find "$STAGING" -type f -perm 0600 -delete
```

Use `-perm 0600` for **exact** match (not `-perm /0600` which is "any of these bits").

### 3. Permission Normalization

```bash
# Directories → 0755
find "$STAGING" -type d -exec chmod 0755 {} +

# Regular files → 0755 if shebang or executable, else 0644
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    first_two="$(head -c2 "$f" 2>/dev/null || true)"
    if [[ "$first_two" == "#!" ]] || [[ -x "$f" ]]; then
        chmod 0755 "$f"
    else
        chmod 0644 "$f"
    fi
done
```

**Shebang detection:** Read first 2 bytes with `head -c2`. Check for `#!` prefix.

### 4. Line Ending Normalization

Convert CRLF → LF for text files only:

```bash
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    enc="$(file -b --mime-encoding "$f")"
    if [[ "$enc" != "binary" ]]; then
        sed -i 's/\r$//' "$f"
    fi
done
```

**Text vs binary detection:** Use `file -b --mime-encoding`. Returns `binary` for binary files, or encoding name (e.g., `us-ascii`, `utf-8`) for text files.

### 5. Deterministic Archive Construction

```bash
export LC_ALL=C  # Critical for consistent sorting

cd "$STAGING"
find . -print0 | sort -z | \
    tar --create \
        --file=- \
        --no-recursion \
        --null -T - \
        --sort=name \
        --format=gnu \
        --owner=0 --group=0 --numeric-owner \
        --mtime="@${EPOCH}" \
    | zstd -19 --long --no-check --single-thread -o /app/release.tar.zst
```

**Critical flags:**
- `LC_ALL=C` — Ensures locale-independent sorting
- `--sort=name` — Deterministic entry ordering
- `--format=gnu` — GNU tar format (not POSIX)
- `--owner=0 --group=0 --numeric-owner` — Normalize ownership to 0:0
- `--mtime="@${EPOCH}"` — Set modification time (use `${SOURCE_DATE_EPOCH:-946684800}` for fallback)
- `--no-recursion --null -T -` — Explicit file list from `find`, prevents tar's own traversal
- `--single-thread` — Deterministic zstd compression

**Symlinks:** Do NOT use `-h` flag (which dereferences symlinks). GNU tar preserves symlinks by default.

### 6. Reproducibility

The archive must be bit-for-bit identical across runs with the same `SOURCE_DATE_EPOCH`:

- Remove output file before zstd: `rm -f /app/release.tar.zst` (zstd refuses to overwrite stdin input otherwise)
- Use `set -euo pipefail` for strict error handling
- Clean staging directory with `trap 'rm -rf "$STAGING"' EXIT`

## Edge Cases

### Special Characters and Long Paths

Use NUL-delimited output throughout:
- `find ... -print0`
- `sort -z`
- `tar --null -T -`
- `while IFS= read -r -d '' f`

This handles:
- Filenames with spaces: `file with spaces.txt`
- Special characters: `file$special\!chars.py`
- Very long paths (>200 chars)
- Deep nesting (30+ levels)

### Empty Directories After Exclusion

When excluding entire directory trees (e.g., `.hg/`, `vendor/js/`), use `rm -rf` to remove the directory and all contents. Don't rely on tar's `--exclude` for this.

### Binary Files with Text-Like Extensions

Some files may have text extensions but contain binary data (e.g., `mixed.dat`). Always use `file --mime-encoding` to detect, never rely on extension.

## Mandatory Verification (Run Before Tests)

**Never submit to tests without verifying the script works first.** This is the most common failure mode — writing a script and immediately running tests without checking if it actually produces correct output.

After writing `build.sh`, run this verification checklist:

```bash
# 1. Run the script and check exit code
bash build.sh
echo $?  # Must be 0

# 2. Check output file exists
ls -la /app/release.tar.zst

# 3. Verify reproducibility (run twice, compare checksums)
md5_1=$(md5sum /app/release.tar.zst | awk '{print $1}')
bash build.sh 2>/dev/null
md5_2=$(md5sum /app/release.tar.zst | awk '{print $1}')
[[ "$md5_1" == "$md5_2" ]] && echo "PASS: Reproducible" || echo "FAIL: Not reproducible"

# 4. Generic exclusion check (read from .distignore dynamically)
echo "Checking patterns from .distignore:"
while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    [[ -z "$pattern" || "$pattern" == \#* ]] && continue
    clean_pattern="${pattern%/}"
    # For directory patterns, check if they appear in archive
    if [[ "$clean_pattern" == */ ]] || [[ "$pattern" == */ ]]; then
        if zstd -d /app/release.tar.zst --stdout | tar -tf - | grep -q "^\.\/${clean_pattern%/}"; then
            echo "  FAIL: $pattern found in archive"
        else
            echo "  PASS: $pattern excluded"
        fi
    fi
done < /app/src/.distignore

# 5. Generic 0600 file check (no hardcoded filenames)
rm -rf /tmp/verify_perms && mkdir -p /tmp/verify_perms
cd /tmp/verify_perms
zstd -d /app/release.tar.zst --stdout | tar -xf - 2>/dev/null
if [[ $(find . -type f -perm 0600 | wc -l) -eq 0 ]]; then
    echo "PASS: No 0600 files in archive"
else
    echo "FAIL: Found 0600 files"
    find . -type f -perm 0600
fi
rm -rf /tmp/verify_perms

# 6. Check symlinks preserved (count should be > 0)
symlink_count=$(zstd -d /app/release.tar.zst --stdout | tar -tvf - | grep "^l" | wc -l)
echo "Symlinks preserved: $symlink_count (should be > 0)"

# 7. Check permissions (should only see -rw-r--r-- and -rwxr-xr-x)
zstd -d /app/release.tar.zst --stdout | tar -tvf - | \
    grep -v "^d" | grep -v "^l" | awk '{print $1}' | sort -u

# 8. Check owner/group (should only see 0/0)
zstd -d /app/release.tar.zst --stdout | tar -tvf - | awk '{print $2}' | sort -u

# 9. Check timestamps (should all be the same date)
zstd -d /app/release.tar.zst --stdout | tar -tvf - | awk '{print $3, $4}' | sort -u

# 10. Test with different SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=1609459200 bash build.sh 2>/dev/null
zstd -d /app/release.tar.zst --stdout | tar -tvf - | head -3 | grep "2021-01-01" && \
    echo "PASS: Timestamps updated" || echo "FAIL: Timestamps not updated"

# 11. Reset to default epoch
bash build.sh 2>/dev/null
md5sum /app/release.tar.zst  # Should match original hash
```

**Only after all checks pass should you run the test suite.** This catches bugs early and saves test attempts.

## Known Pitfalls

### zstd refuses to overwrite existing files from stdin
When piping tar output to `zstd -o output.zst`, zstd will refuse to overwrite an existing file with the error: `already exists; stdin is an input - not proceeding`. **Always `rm -f` the output file before the tar|zstd pipeline**, or use `zstd --force`. This is required because test runners may invoke the build script multiple times.

### `.distignore` parser must match the variant's gitignore dialect
The `case`-based parser in this skill handles three pattern types found in the seed: literal directory paths (`dirname/`), recursive directory matches (`**/dirname/`), and file extension globs (`*.ext`). Variants may introduce additional gitignore syntax:
- Negation patterns (`!pattern`) — must be handled in order after positive matches
- Anchored patterns (leading `/`) — match only at root
- Directory-only vs file-only globs — trailing `/` means directory-only
- Character classes (`[abc]`) — pass through to `find -name`

When facing a new variant, read the `.distignore` file first and extend the parser to cover all pattern types present.

### Text-file detection edge cases
`file --mime-encoding` is reliable for most files but may misclassify:
- Empty files (0 bytes) — typically reported as `binary` or `us-ascii` depending on implementation
- Very short files (< 4 bytes) — may not have enough data for reliable detection
- Files with mixed binary/text content — `file` uses heuristics that may vary

For variants with unusual text-file detection requirements, consider using a whitelist of known text extensions or a custom detection function.

### Empty source files are valid fixtures
Source trees may contain intentionally empty files (0 bytes). The script must preserve them without corruption. `sed -i` on an empty file is safe (no-op), and `file --mime-encoding` on an empty file returns `binary` on most systems, which correctly skips line-ending conversion.

## Variation Dimensions

This skill handles the `deterministic-tarball` family with these axes:

1. **Source tree content and exclusions** — Different directory structures, exclusion patterns, sensitive file rules, symlink cases
2. **Normalization rules** — Different permission schemes, timestamp sources, text-file detection methods, line-ending requirements
3. **Archive format and compression** — Different tar format options, compression levels, environment variables

The core architecture (staging directory, exclusion parsing, permission normalization, deterministic tar flags) remains constant across variants.
