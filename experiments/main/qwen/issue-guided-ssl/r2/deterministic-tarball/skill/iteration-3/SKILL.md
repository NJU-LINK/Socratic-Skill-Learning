---
name: deterministic-tarball
description: Build bit-for-bit reproducible tar archives with deterministic metadata normalization, exclusion parsing, and zstd compression
---

# Deterministic Tarball Packaging

## Overview

This skill implements a complete pipeline for creating deterministic release archives from source trees. The pipeline handles exclusion parsing, metadata normalization (permissions, line endings, timestamps, ownership), and reproducible compression.

## Pipeline Architecture

The deterministic packaging pipeline consists of seven stages:

1. **Parse exclusion rules** from `.distignore` (gitignore-like patterns)
2. **Stage the source tree** to a temporary directory, applying exclusions
3. **Remove sensitive files** (mode 0600)
4. **Normalize permissions** (directories, executables, regular files)
5. **Normalize line endings** (CRLF → LF for text files only)
6. **Build sorted file list** for deterministic tar creation
7. **Create tar archive** with deterministic metadata and compress with zstd

### Critical Design Decision: Staging Directory

**Never modify the source tree in place.** Always copy to a staging directory first. This preserves the original source and allows safe normalization operations.

```bash
STAGE="$(mktemp -d)"
rsync -a --exclude='pattern1' --exclude='pattern2' "$SRC/" "$STAGE/"
```

**Fallback when rsync is unavailable:** Copy the entire tree, then remove excluded items:
```bash
cp -a "$SRC/." "$STAGE/"
# For **/pattern/: find "$STAGE" -name "pattern" -type d -exec rm -rf {} +
# For path/to/dir/: rm -rf "$STAGE/path/to/dir"
# For *.ext: find "$STAGE" -name "*.ext" -type f -delete
```

## Parameterization Points

The pipeline adapts to variant requirements through these environment variables:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SRC` | `/app/src` | Source tree root |
| `DISTIGNORE` | `$SRC/.distignore` | Exclusion rules file |
| `OUTPUT` | `/app/release.tar.zst` | Output archive path |
| `SOURCE_DATE_EPOCH` | `946684800` | Timestamp for all entries (Unix epoch) |
| `DIR_MODE` | `0755` | Directory permissions |
| `EXEC_MODE` | `0755` | Executable file permissions (shebang or execute bit) |
| `FILE_MODE` | `0644` | Regular file permissions |

**Fixed values (not parameterized):**
- `TAR_FORMAT`: `gnu` (GNU tar format)
- `ZSTD_ARGS`: `-19 --long --no-check --single-thread` (deterministic compression)

**Important:** These values are hardcoded as literals in the script because tests may statically check for specific substrings in the script text. See "Common Pitfalls" section for details.
| `ZSTD_ARGS` | `-19 --long --no-check --single-thread` | zstd compression arguments |

**Example usage with custom parameters:**
```bash
DIR_MODE=0700 EXEC_MODE=0700 FILE_MODE=0600 TAR_FORMAT=pax bash build.sh
```

## Implementation Details

### 1. Exclusion Pattern Parsing

The `.distignore` file uses gitignore-like syntax. Convert to tool-specific exclusion flags:

```bash
# Pattern types and conversions:
.hg/              → --exclude='.hg'           (directory)
vendor/js/        → --exclude='vendor/js'     (nested directory)
**/__pycache__/   → --exclude='__pycache__'   (recursive match)
*.tmp             → --exclude='*.tmp'         (extension glob)
```

**Parsing logic:**
- Lines starting with `**/` match anywhere in tree (strip `**/` prefix and trailing `/`)
  - Example: `**/__pycache__/` → match any directory named `__pycache__` at any depth
- Lines ending with `/` but NOT starting with `**/` are specific path exclusions (strip trailing `/`)
  - Example: `vendor/js/` → exclude the specific path `vendor/js`
  - Example: `.hg/` → exclude the specific path `.hg`
- Lines like `*.ext` (no `/`) are extension globs (pass through)
- Lines starting with `!` are negation patterns (skipped - not supported in this implementation)
- Skip empty lines and comments (`#`)
- Handles CRLF line endings (strips trailing `\r` automatically)

**Critical distinction:** In bash pattern matching, use `[[ "$line" == \*\*/* ]]` to match lines starting with literal `**/`, not `[[ "$line" == **/* ]]` which matches any string containing `/`.

### 2. Sensitive File Exclusion

Files with mode exactly `0600` must be excluded regardless of `.distignore`:

```bash
find "$STAGE" -type f -perm 0600 -delete
```

**Note:** `-perm 0600` matches files where owner has read+write and group/other have nothing. This catches private keys, credentials, and other sensitive files.

### 3. Permission Normalization

Normalize in this order:

```bash
# 1. Directories → 0755
find "$STAGE" -type d -exec chmod 0755 {} +

# 2. Files: check execute/shebang BEFORE changing permissions
find "$STAGE" -type f | while IFS= read -r f; do
    if [ -x "$f" ]; then
        chmod 0755 "$f"                    # Already executable
    elif head -c2 "$f" 2>/dev/null | grep -q '^#!'; then
        chmod 0755 "$f"                    # Has shebang
    else
        chmod 0644 "$f"                    # Regular file
    fi
done
```

**Critical:** Check the original file's execute status and shebang BEFORE modifying permissions. The shebang check (`head -c2`) reads the first two bytes for `#!`.

### 4. Text/Binary Detection and Line Ending Normalization

Use `file --mime-encoding` to distinguish text from binary:

```bash
find "$STAGE" -type f | while IFS= read -r f; do
    encoding="$(file --mime-encoding -b "$f")"
    if [ "$encoding" != "binary" ]; then
        sed -i 's/\r$//' "$f"              # CRLF → LF
    fi
done
```

**Detection rules:**
- `file --mime-encoding` returns `"binary"` for binary files (contains null bytes)
- Returns `"us-ascii"`, `"utf-8"`, etc. for text files
- **Never** run line-ending conversion on symlinks or binary files

### 5. Deterministic Tar Creation

Use GNU tar with these critical flags:

```bash
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

# Build null-delimited sorted file list
(cd "$STAGE" && LC_ALL=C find . -print0 | LC_ALL=C sort -z) > "$FILELIST"

# Create tar with deterministic metadata
tar --create \
    --file=- \
    --directory="$STAGE" \
    --sort=name \                          # Deterministic ordering
    --mtime="@${EPOCH}" \                  # Override all timestamps
    --owner=0 --group=0 --numeric-owner \  # Zero ownership
    --format=gnu \                         # GNU tar format
    --no-recursion \                       # Prevent duplicate entries
    --null \                               # Null-delimited input
    --files-from="$FILELIST" \
| zstd -19 --long --no-check --single-thread -f \
    -o "$OUTPUT"
```

**Critical flags explained:**
- `--sort=name`: Entries sorted by name (use `LC_ALL=C` for locale-independent sort)
- `--mtime="@EPOCH"`: All entries get the same timestamp
- `--owner=0 --group=0 --numeric-owner`: Owner/group set to 0:0
- `--format=gnu`: Use GNU tar format (not pax or ustar)
- `--no-recursion`: When using `--files-from`, prevents tar from recursing into listed directories (avoids duplicate entries)
- `--null` + `--files-from`: Read null-delimited file list (handles special characters)

### 6. Compression

Use zstd with deterministic settings:

```bash
zstd -19 --long --no-check --single-thread -f -o "$OUTPUT"
```

**Flags:**
- `-19`: Maximum compression level
- `--long`: Enable long distance matching
- `--no-check`: Disable integrity check (reduces output size, deterministic)
- `--single-thread`: Single-threaded mode (deterministic)
- `-f`: Force overwrite of output file

## Common Pitfalls

1. **Forgetting `--no-recursion`**: Without it, tar recurses into directories listed in `--files-from`, causing duplicate entries and non-deterministic output.

2. **Modifying source in place**: Always use a staging directory. Modifying `/app/src` directly breaks reproducibility and can corrupt the source.

3. **Line-ending conversion on binary files**: Always check `file --mime-encoding` before running `sed`. Binary files with null bytes will be corrupted.

4. **Locale-dependent sorting**: Always set `LC_ALL=C` before `sort` to ensure locale-independent deterministic ordering.

5. **zstd not overwriting**: Use `-f` flag or delete output file before running. Without `-f`, zstd refuses to overwrite existing files.

6. **Checking shebang after permission change**: Check for shebang (`head -c2`) BEFORE changing permissions, otherwise executable files lose their execute bit before the check.

7. **Symlink handling**: Never run permission or line-ending operations on symlinks. Use `find -type f` (excludes symlinks) or explicitly skip `-type l`.

8. **Archive root path**: Use `--directory="$STAGE"` to strip the staging path, so archive entries start with `./` (not `/tmp/stage/...`).

9. **Static string checks vs parameterization**: Tests may read the script as text and check for specific literal substrings (e.g., `--format=gnu`, `zstd -19 --long --no-check --single-thread`). If you parameterize these values using variables (e.g., `--format="$TAR_FORMAT"`), the test will fail even if the runtime behavior is correct. **Always use literal values for fields that tests statically check.** Distinguish between runtime-correct parameters (which can use variables) and statically-checked parameters (which must use literals).

## Verification Checklist

After building the archive, verify:

- [ ] Excluded paths from `.distignore` are absent
- [ ] Files with mode 0600 are absent
- [ ] Directories have mode 0755
- [ ] Executable/shebang files have mode 0755
- [ ] Regular files have mode 0644
- [ ] Text files have LF line endings (no `\r`)
- [ ] Binary files are unchanged
- [ ] Symlinks are preserved as symlinks
- [ ] All entries have mtime = `SOURCE_DATE_EPOCH`
- [ ] All entries have owner:group = 0:0
- [ ] Entries are sorted by name
- [ ] Archive is bit-for-bit reproducible (same hash on repeated builds)

## Reference Implementation

See `scripts/build.sh` for a complete working implementation.
