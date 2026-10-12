---
name: deterministic-tarball
description: Create bit-for-bit reproducible tar archives with metadata normalization, exclusion filtering, and deterministic compression
---

# Deterministic Tarball Creation

## Core Problem

Build release archives that are bit-for-bit reproducible across runs, with controlled metadata normalization and selective file exclusion. The archive must be deterministic: identical inputs produce identical outputs, enabling verification and caching.

## Architectural Pattern: Staging Directory

**Never modify the source tree in-place.** Always work in a staging directory:

```bash
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT
cp -a "$SRC" "$STAGING/root"
```

**Why staging is essential:**
- Preserves the original source tree unchanged
- Allows destructive operations (deletions, permission changes, line ending conversion) without side effects
- Provides full control over what enters the archive
- Enables cleanup via trap on EXIT

**Key detail:** Use `cp -a` (archive mode) which includes `-d` (no-dereference) to preserve symlinks as symlinks rather than copying their targets.

## Exclusion Filtering

### Pattern Semantics

Exclusion rules typically come from a file (e.g., `.distignore`, `.gitignore`). Patterns follow these conventions:

- **Trailing `/`**: directory-only match (e.g., `vendor/` matches only directories named `vendor`)
- **No `/`**: basename match at any depth (e.g., `*.tmp` matches `foo.tmp`, `a/b/c.tmp`)
- **Contains `/`**: path relative to project root (e.g., `vendor/js/` matches only that specific subdirectory)
- **`**/` prefix**: match at any depth (e.g., `**/__pycache__/` matches `__pycache__` anywhere in the tree)

### Implementation Strategy

Process each pattern from the exclusion file:

```bash
while IFS= read -r pattern; do
    # Strip trailing CR if present
    pattern="${pattern%$'\r'}"
    [[ -z "$pattern" || "$pattern" == \#* ]] && continue
    
    if [[ "$pattern" == */ ]]; then
        pattern="${pattern%/}"
        type_flag="-type d"
    else
        type_flag=""
    fi
    
    if [[ "$pattern" == \*\*/* ]]; then
        pattern="${pattern#\*\*/}"
        find "$STAGING/root" $type_flag -name "$pattern" -exec rm -rf {} +
    elif [[ "$pattern" == */* ]]; then
        rm -rf "$STAGING/root/$pattern"
    else
        find "$STAGING/root" $type_flag -name "$pattern" -exec rm -rf {} +
    fi
done < "$DISTIGNORE"
```

**Critical:** Empty parent directories remain after excluding their contents. This is correct behavior—the exclusion targets specific paths, not their ancestors.

## Permission Normalization

### The Ordering Problem

You must **identify executables BEFORE resetting permissions**. If you `chmod 0644` everything first, you lose the execute bit information.

### Correct Sequence

1. **Identify executables** (before any chmod):
   - Files with any execute bit set: `find ... -type f -perm /111`
   - Files with shebang (`#!` in first 2 bytes) but no execute bit
   - **Use null-terminated I/O** (`-print0`, `printf '%s\0'`) to handle filenames with newlines

2. **Reset all permissions**:
   - Directories: `find ... -type d -exec chmod 0755 {} +`
   - Files: `find ... -type f -exec chmod 0644 {} +`

3. **Restore execute permissions**:
   - Apply `chmod 0755` to the identified executables using `xargs -0 -r chmod 0755 < exec_list`

### Implementation

```bash
exec_list=$(mktemp)

# Capture files with execute bit (null-terminated)
find "$STAGING/root" -type f -perm /111 -print0 > "$exec_list"

# Capture files with shebang (null-terminated)
find "$STAGING/root" -type f ! -perm /111 -print0 | while IFS= read -r -d '' f; do
    if [[ -s "$f" ]] && [[ "$(head -c 2 "$f")" == '#!' ]]; then
        printf '%s\0' "$f"
    fi
done >> "$exec_list"

# Reset permissions
find "$STAGING/root" -type d -exec chmod 0755 {} +
find "$STAGING/root" -type f -exec chmod 0644 {} +

# Restore execute permissions
xargs -0 -r chmod 0755 < "$exec_list"
rm -f "$exec_list"
```

**Note:** Check `-s` (non-empty) first. Empty files cannot have shebangs.

### Symlink Considerations

Symlinks don't have their own permissions on Linux. `chmod` on symlinks is a no-op. `tar` will record them as symlinks regardless of the staging directory's symlink permissions.

## Text vs Binary Detection

### Null Byte Method

The most reliable way to distinguish text from binary: **check for null bytes**.

```bash
is_text() {
    [[ ! -s "$1" ]] && return 0  # Empty files are text
    ! grep -qaP '\x00' "$1"      # No null bytes = text
}
```

**Why this works:**
- Text files (ASCII, UTF-8) never contain null bytes
- Binary files (images, compiled objects, data files) typically contain null bytes
- The `file` command can misclassify empty files or unusual text
- **Critical:** The `-a` flag (`--text`) forces grep to treat the file as text and search every byte. Without `-a`, grep may detect the file as binary and skip searching it entirely, causing null-byte detection to silently fail. For example, `red.png` (33 bytes) contains null bytes but `grep -qP '\x00'` (without `-a`) incorrectly reports "no match", while `grep -qaP '\x00'` correctly finds them.

**Edge case:** `mixed.dat` in v01 contains both text lines and binary data with null bytes. Correctly classified as binary, so its content is preserved unchanged.

## Line Ending Normalization

### Text Files Only

Convert CRLF to LF for text files:

```bash
find "$STAGING/root" -type f -print0 | while IFS= read -r -d '' f; do
    if is_text "$f"; then
        sed -i 's/\r$//' "$f"
    fi
done
```

**Why `sed` and not `dos2unix`:**
- `sed` is universally available
- `sed 's/\r$//'` removes trailing CR from each line
- Works correctly on files that already have LF-only endings (no-op)

### Binary Files Unchanged

Binary files must not be processed. Line ending conversion would corrupt binary data.

## mtime Normalization

### Setting Timestamps

```bash
MTIME="${SOURCE_DATE_EPOCH:-946684800}"
find "$STAGING/root" -exec touch -h -d "@$MTIME" {} +
```

**Critical flag:** `-h` (no-dereference) sets mtime on symlinks themselves without following them. Without `-h`, `touch` would modify the symlink target's mtime.

**Default value:** 946684800 = 2000-01-01 00:00:00 UTC (Y2K epoch)

**SOURCE_DATE_EPOCH:** Standard environment variable for reproducible builds. When set, use it; otherwise use the default.

## Deterministic Archive Creation

### Archive Root Structure

**Critical:** Archive entries must be relative to the source root, NOT wrapped in a parent directory. Tests typically expect paths like `app/src/README`, not `root/app/src/README`.

**Wrong approach:**
```bash
cd "$STAGING"
tar ... -T <(find root -print0 | sort -z)  # Creates root/app/src/...
```

**Correct approach:**
```bash
cd "$STAGING/root"
tar ... -T <(find . -print0 | sed -z 's|^\./||' | sort -z)  # Creates app/src/...
```

The `sed -z 's|^\./||'` strips the `./` prefix from `find` output, producing clean relative paths.

### tar Command

```bash
cd "$STAGING/root"
tar --create \
    --file=- \
    --format=gnu \
    --sort=name \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${MTIME}" \
    --null \
    --no-recursion \
    -T <(find . -print0 | sed -z 's|^\./||' | sort -z) \
    | zstd -19 --long --no-check --single-thread > "$OUTPUT"
```

### Key Flags Explained

- **`--format=gnu`**: Use GNU tar format (deterministic, handles long paths)
- **`--sort=name`**: Sort entries by name for deterministic order
- **`--owner=0 --group=0 --numeric-owner`**: Set owner/group to root (0:0) numerically
- **`--mtime="@${MTIME}"`**: Override mtime for all entries (redundant with touch, but ensures consistency)
- **`--null`**: Expect null-terminated input from `-T`
- **`--no-recursion`**: Don't recurse into directories (we provide explicit file list)
- **`-T <(...)`**: Read file list from process substitution

### Why `--no-recursion` with `-T`?

Using `--no-recursion` with an explicit file list (`-T`) gives you full control over:
- Which entries appear in the archive
- The exact order of entries
- Handling of special characters and long paths via null-terminated I/O

Without this, tar's default recursion might include unwanted entries or use non-deterministic ordering.

### Compression

```bash
zstd -19 --long --no-check --single-thread
```

- **`-19`**: Maximum compression level (deterministic)
- **`--long`**: Enable long distance matching (better compression for similar files)
- **`--no-check`**: Don't add checksum to frame (smaller output, still deterministic)
- **`--single-thread`**: Force single-threaded mode (deterministic; multi-threaded zstd can produce different output)

**Why single-threaded?** Multi-threaded zstd may produce different output depending on thread scheduling. Single-threaded mode ensures bit-for-bit reproducibility.

## Symlink Handling

### Preserve as Symlinks

- Use `cp -a` (or `cp -d`) to copy symlinks without dereferencing
- `tar` will record symlinks as symlinks in the archive
- Symlink targets are recorded as-is (absolute or relative paths)

### mtime on Symlinks

Use `touch -h` to set mtime on symlinks themselves. Without `-h`, `touch` follows the symlink and modifies the target.

## Long Paths and Special Characters

### Null-Terminated I/O

Use `-print0` with `find` and `sort -z` to handle:
- File names with spaces
- File names with special characters (`$`, `!`, etc.)
- Very long file names

### GNU tar Format

GNU tar format handles long paths better than older formats (ustar has 100-character limit). The `--format=gnu` flag ensures compatibility.

## Verification Checklist

After building the archive, verify:

1. **Exclusions**: No excluded files/directories present
2. **Permissions**: Directories 0755, files 0644, executables 0755
3. **Line endings**: Text files have LF only, binary files unchanged
4. **mtimes**: All entries have the expected timestamp
5. **Owner/group**: All entries are 0:0 (root:root)
6. **Symlinks**: Preserved as symlinks, not dereferenced
7. **Reproducibility**: Running the build twice produces identical output (same hash)

## Common Pitfalls

### 1. Modifying Source In-Place

**Wrong:** `chmod`, `sed -i`, etc. directly on `/app/src`
**Right:** Copy to staging, modify staging, archive staging

### 2. Permission Normalization Order

**Wrong:** `chmod 0644` everything, then try to find executables
**Right:** Find executables first, then reset, then restore

### 3. Text/Binary Detection

**Wrong:** Using `file` command (unreliable for empty files) or `grep -qP '\x00'` without `-a`
**Right:** Check for null bytes with `grep -qaP '\x00'` (the `-a` flag is mandatory)

Without `-a`, grep may skip binary files entirely during the search, causing null-byte detection to silently fail. A small PNG with null bytes would be incorrectly classified as text, leading to line-ending corruption.

### 4. mtime on Symlinks

**Wrong:** `touch -d "@$MTIME" symlink` (follows symlink)
**Right:** `touch -h -d "@$MTIME" symlink` (no-dereference)

### 5. tar with Null-Terminated Input

**Wrong:** `tar -T <(find ... -print0)` without `--null`
**Right:** `tar --null -T <(find ... -print0 | sort -z)`

### 6. Multi-threaded Compression

**Wrong:** `zstd -19` (may use multiple threads)
**Right:** `zstd -19 --single-thread` (deterministic)

### 7. Archive Root Prefix

**Wrong:** `cd "$STAGING" && tar ... -T <(find root -print0 | sort -z)` (creates `root/app/src/...`)
**Right:** `cd "$STAGING/root" && tar ... -T <(find . -print0 | sed -z 's|^\./||' | sort -z)` (creates `app/src/...`)

Tests expect entries relative to the source root, not wrapped in a parent directory. The `sed -z 's|^\./||'` strips the `./` prefix from `find` output.

## Adaptation Guide

When adapting this skill to different requirements:

### Exclusion Patterns

- Adjust pattern parsing logic based on the exclusion file format
- Handle additional pattern types (regex, negation with `!`, etc.)

### Permission Rules

- Modify the permission values (0755/0644/0755) based on requirements
- Add additional permission categories (e.g., group-writable, setuid)

### Text/Binary Detection

- Adjust detection method if null-byte check is insufficient
- Consider file extensions or MIME types for specific use cases

### Line Ending Requirements

- Change conversion target (LF, CRLF, CR) based on requirements
- Handle mixed line endings within a single file if needed

### mtime Source

- Use different default timestamp if Y2K epoch is inappropriate
- Support additional timestamp sources (file mtime, build timestamp, etc.)

### Archive Format

- Change `--format=gnu` to `--format=pax` or `--format=ustar` if needed
- Adjust compression command (gzip, xz, bzip2) with appropriate flags

### Owner/Group Policy

- Change `--owner=0 --group=0` to preserve original owner/group
- Use `--owner=name --group=name` for specific user/group names

## Family Invariants

These properties are invariant across the deterministic-tarball family:

1. **Staging directory pattern**: Always work in a temp directory, never modify source
2. **Reproducibility requirement**: Bit-for-bit identical output for identical inputs
3. **Metadata normalization**: Permissions, mtimes, owner/group must be controlled
4. **Deterministic ordering**: Archive entries must be sorted consistently
5. **Exclusion filtering**: Some files must be omitted based on rules
6. **Symlink preservation**: Symlinks must be archived as symlinks, not dereferenced

## Spec-Declared Variations

These properties vary according to spec.yaml:

1. **Source tree composition**: Directory names, file types, scale, special cases
2. **Exclusion rules**: Pattern syntax, directory vs file patterns, depth matching
3. **Permission rules**: Specific permission values, executable detection criteria
4. **Text/binary detection**: Detection method, edge case handling
5. **Line ending requirements**: Target line ending, conversion scope
6. **mtime source**: Default timestamp, environment variable name
7. **Archive format**: tar format (gnu/pax/ustar), compression algorithm and flags
8. **Owner/group policy**: Numeric vs named, specific values
