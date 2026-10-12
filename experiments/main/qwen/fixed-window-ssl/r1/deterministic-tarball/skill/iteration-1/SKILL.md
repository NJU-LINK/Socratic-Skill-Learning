---
name: deterministic-tarball
description: Build bit-for-bit reproducible tar archives with proper exclusions, permission normalization, line ending conversion, and deterministic compression
---

# Deterministic Tarball Packaging

Build reproducible release archives from source trees with metadata normalization and exclusion rules.

## Core Pipeline Architecture

**Always use a staging directory** to avoid modifying the source tree:

```bash
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT
cp -a "$SOURCE_DIR" "$STAGING/src"
WORK="$STAGING/src"
```

This makes the script idempotent and safe for repeated runs.

## Exclusion Pattern Conversion

Convert ignore-file patterns (like `.distignore`) to GNU tar `--exclude` format:

### Pattern Rules

1. **Strip trailing `/`** - tar excludes directories and their contents automatically
2. **Strip leading `**/`** - tar doesn't understand gitignore-style `**`; without it, patterns match at any depth
3. **Anchoring logic**:
   - Pattern contains `/` after stripping → anchored to source root → prefix with `src/`
   - Pattern has no `/` → matches at any depth → use as-is

### Examples

| Ignore Pattern | After Stripping | Has `/`? | Tar Exclude Value |
|----------------|-----------------|----------|-------------------|
| `.hg/` | `.hg` | No | `.hg` |
| `vendor/js/` | `vendor/js` | Yes | `src/vendor/js` |
| `**/__pycache__/` | `__pycache__` | No | `__pycache__` |
| `*.tmp` | `*.tmp` | No | `*.tmp` |
| `scratch/` | `scratch` | No | `scratch` |

### Dynamic Exclusions

Find files by permission and add to exclude list:

```bash
find "$WORK" -type f -perm 600 -printf 'src/%P\n' >> "$EXCLUDE_FILE"
```

## Permission Normalization

Apply three rules in order:

```bash
# 1. Directories: 0755
find "$WORK" -type d -exec chmod 0755 {} +

# 2. Regular files: check shebang or execute bit
find "$WORK" -type f -print0 | while IFS= read -r -d '' file; do
    if head -c2 "$file" 2>/dev/null | grep -q '^#!'; then
        chmod 0755 "$file"
    elif [ -x "$file" ]; then
        chmod 0755 "$file"
    else
        chmod 0644 "$file"
    fi
done
```

**Critical**: Use `-type f` to target only regular files. Never chmod symlinks.

## Text vs Binary Detection

Detect text files by checking for NUL bytes:

```bash
if ! grep -qaP '\x00' "$file" 2>/dev/null; then
    # Text file - safe to modify line endings
    sed -i 's/\r$//' "$file"
fi
```

**Important**: The `-a` flag is required. Without it, `grep` treats binary files differently and won't match the pattern correctly.

Binary files (PNG, compiled objects, etc.) contain NUL bytes and are correctly skipped.

## Deterministic Tar Construction

### Required Flags

```bash
LC_ALL=C tar --create \
    --file="$OUTPUT_TAR" \
    --directory="$STAGING" \
    --format=gnu \
    --sort=name \
    --mtime="@$EPOCH" \
    --owner=0 --group=0 --numeric-owner \
    --exclude-from="$EXCLUDE_FILE" \
    src
```

### Key Details

- **`LC_ALL=C`** - Force C locale for deterministic byte-order sorting (critical for cross-environment reproducibility)
- **`--format=gnu`** - Explicitly use GNU tar format
- **`--sort=name`** - Locale-independent byte-order sorting (deterministic)
- **`--mtime=@$EPOCH`** - The `@` prefix means "seconds since epoch"
- **`--owner=0 --group=0 --numeric-owner`** - Force numeric IDs
- **`-C "$STAGING" src`** - Archive the `src` directory naturally; paths become `src/...`
- **Symlinks** - GNU tar preserves symlinks by default (don't use `-h`/`--dereference`)

### Avoid Transform Pitfalls

Don't use `--transform='s,^\.,src,'` with `.` as the tar root. This only transforms the single `.` entry, not all paths. Instead, use `-C staging src` to naturally get `src/` prefixed paths.

## Compression

```bash
zstd -f -19 --long --no-check --single-thread "$OUTPUT_TAR" -o "$OUTPUT_ZST"
```

- **`-f`** - Force overwrite of existing output file (critical for idempotent scripts)
- **`-19`** - Maximum compression level
- **`--long`** - Enable long distance matching
- **`--no-check`** - Omit checksum for reproducibility
- **`--single-thread`** - Deterministic output (multi-threading can vary)

## Special Character Handling

Use null-delimited pipelines throughout:

```bash
find ... -print0 | while IFS= read -r -d '' file; do
    ...
done
```

This correctly handles:
- Spaces in filenames
- Special characters (`$`, `\`, `!`)
- Very long filenames (>200 chars)

## Verification Checklist

After building, verify:

1. **Reproducibility**: Run twice, compare SHA256 hashes
2. **Exclusions**: Check that ignored patterns and 0600 files are absent
3. **Permissions**: Directories 0755, shebang/exec files 0755, others 0644
4. **Line endings**: Text files have LF, binary files unchanged
5. **Timestamps**: All entries show the correct epoch time
6. **Owner/group**: All entries show 0/0
7. **Symlinks**: Preserved as symlinks, not dereferenced
8. **Archive structure**: Paths start with `src/`

## Common Pitfalls

1. **Modifying source in place** - Always use staging directory
2. **Incorrect NUL detection** - Must use `grep -qaP '\x00'` with `-a` flag
3. **Transform only affects root** - Use `-C staging src` instead
4. **Tar `**` handling** - Strip `**/` prefix; tar doesn't understand gitignore globs
5. **Chmod on symlinks** - Use `-type f` to target only regular files
6. **Missing `-a` in grep** - Binary file detection fails without it
7. **zstd overwrite prompt** - Must use `-f` flag or `rm -f` before compressing; without it, zstd prompts interactively and fails in non-interactive mode when output file exists
8. **Locale-dependent sorting** - `--sort=name` respects `LC_COLLATE`; must prefix with `LC_ALL=C` for deterministic byte-order across environments

## Adaptation Guide

When adapting to variants:

- **Different ignore file format** - Adjust pattern conversion logic
- **Different permission rules** - Modify the three-rule normalization
- **Different text detection** - May need custom binary detection (e.g., MIME type)
- **Different compression** - Adjust zstd flags or switch compressor
- **Different archive root** - Change the directory passed to tar
- **Different timestamp source** - Adjust `SOURCE_DATE_EPOCH` fallback
