---
name: deterministic-tarball
description: Build bit-for-bit reproducible tar archives with deterministic metadata normalization, exclusion rules, and compression
---

# Deterministic Tarball Packaging

## Overview

This skill creates reproducible release archives from source trees by normalizing metadata, applying exclusion rules, and using deterministic compression. The output is bit-for-bit identical for identical inputs.

## Core Procedure

The packaging follows a **staging directory pattern**: copy → exclude → normalize → list → archive.

```bash
# 1. Create staging area
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# 2. Copy source tree CONTENTS preserving symlinks
#    Copy contents of SRC_DIR to STAGING root (not SRC_DIR itself)
cp -a "$SRC_DIR/." "$STAGING/"

# 3. Apply exclusions (from .distignore + custom rules)
# 4. Clean empty directories
# 5. Normalize line endings (text files only)
# 6. Normalize permissions
# 7. Build sorted file list
# 8. Create deterministic tar + compress
```

**Critical**: Copy the *contents* of the source directory, not the directory itself. This ensures archive paths are relative to the source root (e.g., `app/src/main.c`) rather than nested under a subdirectory (e.g., `src/app/src/main.c`).

## Exclusion Rule Parsing

Parse `.distignore` (gitignore-style patterns) with three cases:

1. **Recursive globs** (`**/__pycache__/`): Strip `**/` prefix, match basename at any depth
   ```bash
   find "$STAGING" -type d -name "__pycache__" -exec rm -rf {} +
   ```

2. **Path patterns** (`vendor/js/`): Treat as literal path relative to source root
   ```bash
   rm -rf "$STAGING/vendor/js"
   ```

3. **Simple names/globs** (`*.tmp`, `.hg`): Match by name at any depth
   ```bash
   find "$STAGING" -name "*.tmp" -exec rm -rf {} +
   ```

**Additional exclusions**: Files with mode exactly 0600 (sensitive files)
```bash
find "$STAGING" -type f -perm 0600 -delete
```

**Empty directory cleanup** (after all exclusions):
```bash
find "$STAGING" -mindepth 1 -type d -empty -delete
```

## Text vs Binary Detection

Use `file --mime-encoding` to distinguish text from binary:

```bash
encoding=$(file -b --mime-encoding "$filepath")
if [ "$encoding" != "binary" ]; then
    # Text file: convert CRLF → LF
    sed -i 's/\r$//' "$filepath"
fi
```

**Critical**: Only modify files where encoding is NOT "binary". Files with embedded null bytes or mixed content are classified as binary and left unchanged.

## Permission Normalization

Apply after exclusions and line-ending normalization:

```bash
# Directories: 0755
find "$STAGING" -type d -exec chmod 0755 {} +

# Regular files: check execute or shebang
find "$STAGING" -type f | while IFS= read -r filepath; do
    # Also check original source permissions as fallback
    orig_file="$SRC_DIR/${filepath#$STAGING/}"
    if [ -x "$filepath" ] || [ -x "$orig_file" ] 2>/dev/null; then
        chmod 0755 "$filepath"
    elif head -c 2 "$filepath" 2>/dev/null | grep -q '#!'; then
        chmod 0755 "$filepath"
    else
        chmod 0644 "$filepath"
    fi
done
```

**Shebang detection**: Check first 2 bytes for `#!`. This catches scripts that lost execute permission.

**Original permission fallback**: Check the original source file's execute bit as a fallback, in case `cp -a` doesn't perfectly preserve permissions across different filesystems or umask settings.

## Deterministic Archive Creation

Build sorted file list relative to staging directory:

```bash
cd "$STAGING"
find . -mindepth 1 | sed 's|^\./||' | LC_ALL=C sort > "$FILELIST"
```

Create tar with deterministic flags:

```bash
tar --create \
    --format=gnu \
    --sort=name \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${EPOCH}" \
    --no-recursion \
    -C "$STAGING" \
    --files-from="$FILELIST" \
    | zstd -19 --long --no-check --single-thread > "$OUTPUT"
```

**Critical tar flags**:
- `--format=gnu`: Use GNU tar format
- `--sort=name`: Sort entries by name
- `--owner=0 --group=0 --numeric-owner`: Set owner/group to 0:0
- `--mtime="@${EPOCH}"`: Set modification time (use SOURCE_DATE_EPOCH or default)
- `--no-recursion`: Don't recurse into directories (use explicit file list)
- `-C "$STAGING"`: Change to staging directory (must come before `--files-from`)

**Symlink handling**: Do NOT use `-h` flag. GNU tar preserves symlinks by default.

**zstd flags**:
- `-19`: Maximum compression level
- `--long`: Enable long distance matching
- `--no-check`: Disable checksum (deterministic)
- `--single-thread`: Single-threaded (deterministic)

## Timestamp Handling

```bash
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"
```

Use `SOURCE_DATE_EPOCH` environment variable if set, otherwise default to 946684800 (2000-01-01 00:00:00 UTC).

## Verification Checklist

After building the archive, verify:

1. **Exclusions applied**: No .distignore patterns, no 0600 files, no empty directories
2. **Line endings**: Text files use LF only (check with `od -c`)
3. **Permissions**: Dirs 0755, executables/shebangs 0755, regular files 0644
4. **Symlinks preserved**: Listed as `lrwxrwxrwx` in `tar -tv` output
5. **Metadata normalized**: All entries show owner/group 0/0, same mtime
6. **Reproducibility**: Run twice with same SOURCE_DATE_EPOCH, compare with `diff`

## Variant Considerations

**What changes across variants**:
- Source tree structure and file types
- `.distignore` patterns (different exclusion rules)
- Permission rules (different chmod values)
- Timestamp source (different epoch or default)
- Archive format options (different tar format)
- Compression settings (different zstd level)

**What stays invariant**:
- Staging directory pattern (copy → exclude → normalize → list → archive)
- Deterministic tar flags for reproducibility
- Text vs binary detection approach
- Empty directory cleanup after exclusions
- Symlink preservation (no `-h` flag)
- `-C` flag positioning in tar command

## Common Pitfalls

1. **`-C` flag position**: Must come before `--files-from`, otherwise tar ignores it
2. **Archive root prefix**: Copy source *contents* to staging root (e.g., `cp -a "$SRC_DIR/." "$STAGING/"`), not the directory itself. Otherwise archive paths will have an unwanted prefix like `src/`
3. **File list path stripping**: When building the file list with `find . -mindepth 1`, strip the `./` prefix using `sed 's|^\./||'` so paths are clean relative paths
4. **Empty directories**: Must clean up after exclusions, otherwise archive contains empty dirs
5. **Text detection**: Use `file --mime-encoding`, not `file` description strings
6. **Shebang detection**: Check execute permission OR shebang, not just one
7. **Symlinks**: Don't use `tar -h` (follows symlinks), let tar preserve them
8. **Pattern parsing**: Handle all three cases (recursive globs, paths, simple names)

## Reference Implementation

See `scripts/build.sh` for a complete working implementation.
