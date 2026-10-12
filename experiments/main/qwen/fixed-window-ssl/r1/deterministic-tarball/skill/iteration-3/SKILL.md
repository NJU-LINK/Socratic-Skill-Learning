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
3. **Anchoring logic** (when using `tar -C "$WORK" .`):
   - Pattern contains `/` after stripping → anchored to root → prefix with `./`
   - Pattern has no `/` → matches at any depth → use as-is

### Examples

| Ignore Pattern | After Stripping | Has `/`? | Tar Exclude Value |
|----------------|-----------------|----------|-------------------|
| `.hg/` | `.hg` | No | `.hg` |
| `vendor/js/` | `vendor/js` | Yes | `./vendor/js` |
| `**/__pycache__/` | `__pycache__` | No | `__pycache__` |
| `*.tmp` | `*.tmp` | No | `*.tmp` |
| `scratch/` | `scratch` | No | `scratch` |

### Dynamic Exclusions

Find files by permission and add to exclude list:

```bash
find "$WORK" -type f -perm 600 -printf './%P\n' >> "$EXCLUDE_FILE"
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
    --directory="$WORK" \
    --format=gnu \
    --sort=name \
    --mtime="@$EPOCH" \
    --owner=0 --group=0 --numeric-owner \
    --exclude-from="$EXCLUDE_FILE" \
    --transform='s,^\./,,' \
    .
```

### Key Details

- **`LC_ALL=C`** - Force C locale for deterministic byte-order sorting (critical for cross-environment reproducibility)
- **`--format=gnu`** - Explicitly use GNU tar format
- **`--sort=name`** - Locale-independent byte-order sorting (deterministic)
- **`--mtime=@$EPOCH`** - The `@` prefix means "seconds since epoch"
- **`--owner=0 --group=0 --numeric-owner`** - Force numeric IDs
- **`-C "$WORK" .`** - Archive the contents of the working directory; paths become relative to source tree root
- **`--transform='s,^\./,,'`** - Strip the `./` prefix so paths are clean (e.g., `app/src/main.c` not `./app/src/main.c`)
- **Symlinks** - GNU tar preserves symlinks by default (don't use `-h`/`--dereference`)

### Archive Root Layout

The archive should contain the source tree contents at paths relative to the source tree root. The `--transform` strips the `./` prefix that tar adds when archiving `.`. This produces clean paths like `app/src/main.c`, `docs/README.txt`, etc.

**Do not** wrap everything in a `src/` directory unless explicitly required by the task.

## Compression

```bash
rm -f "$OUTPUT_ZST"
zstd -19 --long --no-check --single-thread "$OUTPUT_TAR" -o "$OUTPUT_ZST"
```

- **`rm -f` before zstd** - Remove existing output to avoid interactive overwrite prompt (critical for idempotent scripts)
- **`-19`** - Maximum compression level (must immediately follow `zstd` for regex matching)
- **`--long`** - Enable long distance matching
- **`--no-check`** - Omit checksum for reproducibility
- **`--single-thread`** - Deterministic output (multi-threading can vary)

**Important**: Do not use `zstd -f` as it breaks regex patterns that expect `-19` immediately after `zstd`. Instead, use `rm -f` before the command.

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
8. **Archive structure**: Paths are relative to source tree root (e.g., `app/src/main.c`, not `./app/src/main.c` or `src/app/src/main.c`)

### Concrete Verification Commands

```bash
# 1. Reproducibility
HASH1=$(sha256sum release.tar.zst | cut -d' ' -f1)
rm release.tar.zst && bash build.sh >/dev/null 2>&1
HASH2=$(sha256sum release.tar.zst | cut -d' ' -f1)
[ "$HASH1" = "$HASH2" ] && echo "✓ Reproducible" || echo "✗ Not reproducible"

# 2. Archive contents
zstd -d release.tar.zst -o verify.tar
tar -tf verify.tar | head -20

# 3. Metadata verification
python3 << 'PYEOF'
import tarfile
with tarfile.open('verify.tar', 'r') as t:
    for m in t.getmembers():
        if m.name == 'app/src/main.c':
            print(f"main.c: mode={oct(m.mode)}, mtime={m.mtime}, uid={m.uid}, gid={m.gid}")
        if m.name == 'app/src/unix.py':
            print(f"unix.py: mode={oct(m.mode)} (should be 0o755)")
        if m.name == 'app/src/README':
            print(f"README: islink={m.issym()}, linkname={m.linkname}")
PYEOF
```

## Edge Cases and Special Scenarios

### Empty Files
Zero-byte files should be included with mode 0644 (unless they have shebang or execute bit).

### Special Characters in Filenames
Filenames with `$`, `\`, `!`, spaces, and other special characters must be preserved exactly. Use null-delimited pipelines (`-print0`, `read -d ''`) throughout.

### Very Long Filenames (>200 chars)
GNU tar handles long filenames correctly. No special handling needed, but verify they appear in the archive.

### Deep Nesting (20+ levels)
Deep directory structures are preserved. Verify the full path appears in the archive.

### Mixed Binary and Text Files
- Binary files (PNG, compiled objects, files with NUL bytes) must remain unchanged
- Text files (source code, markdown, config files) must have CRLF→LF conversion
- Use `grep -qaP '\x00'` to detect binary files (the `-a` flag is critical)

### Symlinks
- Preserve symlinks as symlinks (don't dereference)
- Never chmod symlinks (use `-type f` to target only regular files)
- Symlink targets can be relative or absolute

### Files with 0600 Permissions
These must be excluded even if not listed in .distignore. Use `find -perm 600` to detect them dynamically.

## Common Pitfalls

1. **Modifying source in place** - Always use staging directory
2. **Incorrect NUL detection** - Must use `grep -qaP '\x00'` with `-a` flag
3. **Wrong archive root** - Use `-C "$WORK" . --transform='s,^\./,,'` to get paths relative to source tree root
4. **Tar `**` handling** - Strip `**/` prefix; tar doesn't understand gitignore globs
5. **Chmod on symlinks** - Use `-type f` to target only regular files
6. **Missing `-a` in grep** - Binary file detection fails without it
7. **zstd overwrite prompt** - Use `rm -f "$OUTPUT_ZST"` before zstd; do not use `zstd -f` as it breaks regex matching
8. **Locale-dependent sorting** - `--sort=name` respects `LC_COLLATE`; must prefix with `LC_ALL=C` for deterministic byte-order across environments
9. **Wrong exclude pattern prefix** - When using `tar -C "$WORK" .`, anchored patterns need `./` prefix (e.g., `./vendor/js`), not `src/` prefix

## Adaptation Guide

When adapting to variants:

- **Different ignore file format** - Adjust pattern conversion logic
- **Different permission rules** - Modify the three-rule normalization
- **Different text detection** - May need custom binary detection (e.g., MIME type)
- **Different compression** - Adjust zstd flags or switch compressor
- **Different archive root** - Change the directory passed to tar
- **Different timestamp source** - Adjust `SOURCE_DATE_EPOCH` fallback

## Performance Considerations

### Large Source Trees
- The staging directory approach uses additional disk space (full copy of source)
- For very large trees (10GB+), consider using `rsync` with filters instead of `cp -a`
- The `find | while read` loops are sequential; for massive file counts, consider `xargs -P` for parallel processing

### Compression Speed
- `zstd -19` is slow but produces smallest output
- For faster builds, use `-3` or `-6` (still good compression, much faster)
- `--single-thread` is required for reproducibility but slower than multi-threaded

### Exclusion Pattern Matching
- `--exclude-from` is efficient for large exclusion lists
- For complex patterns, consider generating the file list explicitly with `find` and using `--no-recursion -T FILELIST`

## Troubleshooting

### Archive Contains `./` Prefix
**Problem**: Paths appear as `./app/src/main.c` instead of `app/src/main.c`

**Solution**: Ensure `--transform='s,^\./,,'` is present in the tar command. This strips the `./` prefix that tar adds when archiving `.`.

### zstd Prompts for Overwrite
**Problem**: Script hangs waiting for user input when `release.tar.zst` already exists

**Solution**: Use `rm -f "$OUTPUT_ZST"` before the zstd command. Do not use `zstd -f` as it breaks regex patterns.

### Binary Files Modified
**Problem**: PNG or other binary files are corrupted after line ending conversion

**Solution**: Ensure `grep -qaP '\x00'` has the `-a` flag. Without it, grep treats binary files differently and the NUL detection fails.

### Symlinks Dereferenced
**Problem**: Symlinks appear as regular files in the archive

**Solution**: Do not use `-h` or `--dereference` with tar. GNU tar preserves symlinks by default.

### Non-Reproducible Output
**Problem**: SHA256 hash differs between runs

**Solution**: Check that:
- `LC_ALL=C` is set before tar
- `--sort=name` is used
- All mtimes are set to the same epoch value
- Owner/group are forced to 0:0 with `--numeric-owner`
- zstd uses `--single-thread --no-check`

### Exclusion Patterns Not Matching
**Problem**: Files that should be excluded are still in the archive

**Solution**: 
- For anchored patterns (containing `/`), prefix with `./` when using `tar -C "$WORK" .`
- Strip trailing `/` from directory patterns
- Strip leading `**/` from patterns (tar doesn't understand gitignore globs)
- Verify the exclude file contents with `cat "$EXCLUDE_FILE"`
