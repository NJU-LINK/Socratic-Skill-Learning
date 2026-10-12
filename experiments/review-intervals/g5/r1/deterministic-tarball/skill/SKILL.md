---
name: deterministic-tarball
description: Build bit-for-bit reproducible tar archives with metadata normalization, exclusion patterns, and deterministic compression
---

# Deterministic Tarball Packaging

Build reproducible release archives from source trees with controlled exclusions, normalized metadata, and deterministic compression.

## Core Architecture

**Staging Directory Pattern**: Copy source tree to a temporary staging area, normalize in-place, then archive. This avoids modifying the original source and gives full control over metadata transformation.

```bash
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
cp -a "$SRC"/. "$STAGING"/
```

Why `cp -a`: preserves symlinks (not dereferenced), permissions, and timestamps. The staging area is a sandbox where destructive normalization is safe.

## Critical Operation Ordering

The steps below MUST execute in this exact order. Each step depends on state from the previous step:

```
1. Copy source tree         → preserves original permissions for inspection
2. Parse exclusion rules    → needed before any file operations
3. Delete 0600 files        → removes sensitive files before permission normalization
4. Record execute perms     → MUST happen before chmod (which destroys this info)
5. Normalize permissions    → chmod everything to baseline (0644/0755)
6. Restore executability    → re-apply +x from recorded list + shebang detection
7. Normalize line endings   → MUST happen after permissions (sed -i needs writable files)
8. Create archive           → last step; reads final state of staging area
```

**Why this ordering matters**:
- Step 4 before 5: If you chmod first, all files become 0644 and you lose the information about which files originally had +x. You must snapshot this state before normalization.
- Step 7 after 5: `sed -i` creates a temporary file and replaces the original. If the original is read-only (e.g., mode 0444), sed -i fails. Normalizing permissions first ensures all files are writable.
- Step 3 before 5: Sensitive files (0600) must be removed before the blanket chmod would change their permissions, making them harder to identify.

## Methodology

### 1. Exclusion Pattern Conversion

Read exclusion rules from a `.distignore` file (gitignore-style patterns) and convert to tar `--exclude` flags:

```bash
EXCLUDES=()
if [[ -f "$STAGING/.distignore" ]]; then
    while IFS= read -r pattern || [[ -n "$pattern" ]]; do
        [[ -z "$pattern" || "$pattern" == \#* ]] && continue
        pattern="${pattern%/}"           # Strip trailing slash
        pattern="${pattern#\*\*/}"       # Strip leading **/ prefix
        EXCLUDES+=( "--exclude=$pattern" )
    done < "$STAGING/.distignore"
fi
```

**GNU tar pattern matching**: `--exclude` matches at any depth by default. So `**/__pycache__/` becomes `--exclude='__pycache__'` and matches `__pycache__` anywhere in the tree. Trailing `/` on directory patterns is stripped because tar matches directories implicitly.

**Pattern types handled**:
- `dirname/` → `--exclude='dirname'` (directory at any depth)
- `path/to/dir/` → `--exclude='path/to/dir'` (specific path)
- `*.ext` → `--exclude='*.ext'` (glob at any depth)
- `**/pattern/` → `--exclude='pattern'` (explicit recursive)

### 2. Sensitive File Exclusion

Remove files with restricted permissions regardless of exclusion patterns:

```bash
find "$STAGING" -type f -perm 0600 -delete
find "$STAGING" -mindepth 1 -type d -empty -delete 2>/dev/null || true
```

The second `find` cleans up directories left empty after file deletion (e.g., `secrets/` after removing `secrets/db.conf`).

### 3. Permission Normalization

```bash
# CRITICAL: Record execute permission BEFORE any chmod
# Use /111 to detect ANY execute bit (user, group, or other)
# Do NOT use /u+x — it misses files with only group/other execute
EXEC_LIST="$(mktemp)"
find "$STAGING" -type f -perm /111 -print0 > "$EXEC_LIST"

# Baseline: directories 0755, files 0644
find "$STAGING" -type d -exec chmod 0755 {} +
find "$STAGING" -type f -exec chmod 0644 {} +

# Restore execute on files that originally had any execute bit
while IFS= read -r -d '' f; do
    chmod 0755 "$f"
done < "$EXEC_LIST"
rm -f "$EXEC_LIST"

# Also mark files with shebang (#!) as executable
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    if head -c 2 "$f" 2>/dev/null | grep -q '^#!'; then
        chmod 0755 "$f"
    fi
done
```

**Edge cases handled**:
- Read-only files (mode 0444): `chmod 0644` overrides the read-only bit
- Files that are both +x AND have shebang: handled correctly (chmod is idempotent)
- Empty files: `head -c 2` returns nothing, grep fails, file stays 0644 (correct)

### 4. Text/Binary Detection and Line Ending Normalization

```bash
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    [[ -L "$f" ]] && continue      # Skip symlinks
    [[ ! -s "$f" ]] && continue    # Skip empty files (no content to convert)

    # Binary detection via NUL-byte presence
    if tr -d '\0' < "$f" | cmp -s - "$f"; then
        sed -i 's/\r$//' "$f"      # Text: CRLF → LF
    fi
    # Binary: left unchanged
done
```

**Why `tr -d '\0' | cmp -s` and NOT `grep -P '\x00'`**:
`grep -P '\x00'` is unreliable across environments. In many implementations (including GNU grep on common Linux distros), grep treats NUL bytes as string terminators or silently skips them, causing false negatives. The `tr`+`cmp` method is deterministic: strip all NUL bytes, compare with original. If they differ, the file had NUL bytes (binary). If identical, no NUL bytes (text).

**Edge cases handled**:
- PNG files with embedded `0d 0a` sequences (part of PNG format): detected as binary due to NUL bytes elsewhere, left unchanged
- Mixed content files (text + NUL bytes): correctly classified as binary
- Empty files: skipped (no content to convert, `sed` would be a no-op anyway)
- Symlinks: skipped entirely (not regular files for line ending purposes)

### 5. Filename Safety

Always use null-delimited iteration for files with spaces, special characters, or long names:

```bash
find . -type f -print0 | while IFS= read -r -d '' f; do
    # "$f" is safe regardless of content
done
```

### 6. Deterministic Archive Creation

```bash
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

tar --create \
    --file=- \
    --format=gnu \
    --sort=name \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${SOURCE_DATE_EPOCH}" \
    ${EXCLUDES[@]+"${EXCLUDES[@]}"} \
    -C "$STAGING" . \
| zstd -19 --long --no-check --single-thread -o "$OUTPUT"
```

**Flag purposes**:
- `--sort=name`: Deterministic entry ordering (alphabetical)
- `--owner=0 --group=0 --numeric-owner`: Fixed numeric ownership, no name lookup
- `--mtime="@${SOURCE_DATE_EPOCH}"`: Fixed timestamp for all entries (`@` = epoch seconds)
- `--format=gnu`: GNU tar format
- No `--dereference`/`-h`: Symlinks preserved as symlinks
- `-C "$STAGING" .`: Archive relative paths from staging root

**Compression flags**:
- `-19`: Maximum compression level
- `--long`: Enable long-range matching for better compression
- `--no-check`: Omit checksum in frame (saves bytes, reproducibility via tar content)
- `--single-thread`: Deterministic (multi-threaded zstd may produce different output)

### 7. Re-run Safety

```bash
rm -f "$OUTPUT"
```

`zstd -o` refuses to overwrite existing files when reading from stdin. Remove the output file first to allow repeated runs.

## Verification Checklist

Run these after every build:

1. **Reproducibility**: Build twice, compare SHA256 — must be identical
2. **Exclusions**: `tar -tf` and grep for excluded patterns — none should appear
3. **Sensitive files**: Verify 0600-mode files are absent
4. **Symlinks**: `tar -tvf | grep "^l"` — should show preserved symlinks
5. **Permissions**: Directories 0755, executables 0755, regular files 0644
6. **Line endings**: Extract and hex-dump text files — no `0d 0a` sequences
7. **Binary preservation**: Extract and hex-dump binary files — unchanged from source
8. **Metadata**: All entries show `0/0` owner/group and correct mtime
9. **SOURCE_DATE_EPOCH**: Test with different values — mtime should change accordingly

## Common Pitfalls

1. **`grep -P '\x00'` fails silently**: Returns false even on files with NUL bytes. Use `tr -d '\0' | cmp -s`.
2. **zstd overwrite refusal**: `zstd -o` won't overwrite. Add `rm -f "$OUTPUT"` before pipeline.
3. **Filename splitting on spaces**: `for f in $(find ...)` breaks on spaces. Use `-print0 | read -d ''`.
4. **Permission ordering**: Recording execute bits AFTER chmod gives empty results. Record BEFORE.
5. **Execute bit detection scope**: `-perm /u+x` only catches user-execute. Use `-perm /111` to catch any execute bit (user, group, or other). Files with only group/other execute would otherwise lose their executable status.
6. **sed -i on read-only files**: Fails silently or errors. Normalize permissions first.
7. **mtime format**: `--mtime="946684800"` is interpreted as a date string. Use `--mtime="@946684800"` for epoch seconds.
8. **Empty directories after deletion**: After removing sensitive files, clean up empty parent dirs.
9. **Empty array with `set -u`**: `"${EXCLUDES[@]}"` fails with "unbound variable" in bash < 4.4 when the array is empty. Use `${EXCLUDES[@]+"${EXCLUDES[@]}"}` for safe expansion across all bash versions.

## Task Description Parsing Guide

When facing a new variant, extract these parameters from the task description:

| Parameter | What to look for | Default (if unspecified) |
|-----------|------------------|--------------------------|
| Exclusion file | Path and format of ignore rules | `.distignore` with gitignore patterns |
| Sensitive mode | Which file mode to auto-exclude | `0600` |
| Dir permissions | Target mode for directories | `0755` |
| Exec permissions | Target mode for executables | `0755` |
| File permissions | Target mode for regular files | `0644` |
| Exec detection | How to identify executables | Shebang (`#!`) OR existing +x |
| Line endings | Target line ending for text files | LF |
| Binary detection | How to distinguish text from binary | NUL-byte presence |
| Timestamp | Source and default mtime | `SOURCE_DATE_EPOCH` env or `946684800` |
| Owner/group | Numeric uid:gid for archive entries | `0:0` |
| Tar format | Archive format flag | `gnu` |
| Sort order | Entry ordering | `name` (alphabetical) |
| Compression | Tool and flags | `zstd -19 --long --no-check --single-thread` |
| Output path | Where to write the archive | Task-specified |
| Symlinks | Preserve or dereference | Preserve |

## Adaptation Examples

**Different permission scheme** (e.g., 0775 dirs, 0664 files):
```bash
find "$STAGING" -type d -exec chmod 0775 {} +
find "$STAGING" -type f -exec chmod 0664 {} +
# Restore +x as before
```

**Different line endings** (e.g., CRLF output):
```bash
# Convert LF to CRLF instead
sed -i 's/\r$//' "$f"   # First normalize to LF
sed -i 's/$/\r/' "$f"   # Then add CR
```

**Different compression** (e.g., gzip):
```bash
tar ... | gzip -9 -n > "$OUTPUT"   # -n for no timestamp in gzip header
```

**Different archive root** (e.g., files under `project/` prefix):
```bash
# Instead of -C "$STAGING" ., create a wrapper directory:
mkdir -p "$WRAP/project"
cp -a "$STAGING"/. "$WRAP/project"/
tar ... -C "$WRAP" .
```
