---
name: deterministic-tarball
description: Build bit-for-bit reproducible tar.zst archives from source trees with exclusion rules, permission/line-ending normalization, and deterministic compression
---

# Deterministic Tarball Packaging

Build reproducible release archives from source trees with controlled exclusions, metadata normalization, and deterministic compression.

## Core Architecture

Use a **staging-area pattern** — never modify the source tree in-place:

```
source_tree → staging_copy → apply_exclusions → normalize_metadata → tar | zstd → output
```

The staging area isolates all transformations and allows safe permission/line-ending changes without affecting the original source.

## Implementation Steps

### 1. Staging Copy with Symlink Preservation

```bash
STAGING="/tmp/release-staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -a "$SRC"/. "$STAGING"/
```

**Critical**: `cp -a` includes `-d` (no-dereference) which preserves symlinks as symlinks. Never use `cp -r` alone — it follows symlinks and copies target content.

### 2. Parse Exclusion Rules (.distignore)

The `.distignore` file uses gitignore-style patterns. Parse line-by-line, handling:

- **Blank lines and comments** (lines starting with `#`): skip
- **`**` patterns** (e.g., `**/__pycache__/`): match at any depth
  - Strip leading `**/` and trailing `/`
  - Use `find -type d -name "$base" -exec rm -rf {} +` for directories
  - Use `find -type f -name "$pattern" -delete` for file globs
- **Directory patterns** (trailing `/`): remove from staging root
  - `rm -rf "$STAGING/${pattern%/}"`
- **File glob patterns** (contain `*` or `?`): match at any depth
  - `find "$STAGING" -type f -name "$pattern" -delete`
- **Literal paths**: remove from staging root
  - `rm -rf "$STAGING/$pattern"`

**The `**` gotcha**: `**/__pycache__/` does NOT mean a literal `**` directory. It means "match `__pycache__` at any depth." Always strip the `**/` prefix before matching.

### 3. Exclude Sensitive Files (0600 Mode)

```bash
find "$STAGING" -type f -perm 0600 -delete
```

`-perm 0600` matches **exactly** mode 0600 (owner read/write only). This catches SSH keys, secrets, and other sensitive files. Use `-type f` to avoid matching directories or symlinks.

### 4. Normalize Permissions (Order Matters!)

**Check shebang/execute BEFORE chmod** — once you change permissions, you lose the execute-bit signal.

```bash
# Directories → 0755
find "$STAGING" -type d -exec chmod 0755 {} +

# Regular files: shebang OR execute → 0755, else → 0644
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    if [ -x "$f" ] || { [ -s "$f" ] && head -c 2 "$f" | grep -q '^#!'; }; then
        chmod 0755 "$f"
    else
        chmod 0644 "$f"
    fi
done
```

**Why this order**: If you `chmod 0644` first, you lose the execute bit. The check is: "does the file currently have execute permission OR start with `#!`?"

**Safety**: Use `-print0` and `read -d ''` for filenames with spaces/special chars. Never `chmod` symlinks — it changes the target's permissions.

### 5. Normalize Line Endings (Text Files Only)

```bash
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    encoding=$(file --mime-encoding -b "$f" 2>/dev/null || echo "binary")
    if [ "$encoding" != "binary" ]; then
        sed -i 's/\r$//' "$f"
    fi
done
```

**Text/binary detection**: `file --mime-encoding -b` returns encoding (e.g., `us-ascii`, `utf-8`) for text and `binary` for binary files. This is the most reliable method on standard Linux.

**Fallback** if `file --mime-encoding` unavailable: check for null bytes:
```bash
if ! grep -Pql '\x00' "$f" 2>/dev/null; then
    sed -i 's/\r$//' "$f"
fi
```

**Critical**: Only process regular files, never symlinks. `sed -i` on a symlink follows it and modifies the target.

### 6. Deterministic Tar Creation

```bash
MTIME="${SOURCE_DATE_EPOCH:-946684800}"

tar --create \
    --file=- \
    --format=gnu \
    --sort=name \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${MTIME}" \
    -C "$STAGING" \
    . \
| zstd -19 --long --no-check --single-thread -f -o "$OUTPUT"
```

**Every flag explained**:
- `--format=gnu`: GNU tar format (handles long filenames natively)
- `--sort=name`: **Critical for determinism** — sorts entries alphabetically regardless of filesystem order
- `--owner=0 --group=0 --numeric-owner`: Sets UID/GID to 0:0, stores numeric values (not name lookups)
- `--mtime="@${MTIME}"`: The `@` prefix means "seconds since epoch." Overrides all file timestamps
- `-C "$STAGING" .`: Changes to staging dir, archives `.` (paths become `./file`, `./dir/file`, etc.)
- `--file=-`: Write to stdout for piping

**Zstd flags**:
- `-19`: Maximum compression level
- `--long`: Long-distance matching mode
- `--no-check`: Disable content checksum
- `--single-thread`: **Critical for determinism** — multi-threaded compression produces different chunk boundaries
- `-f`: Force overwrite of existing output file

### 7. Cleanup

```bash
rm -rf "$STAGING"
```

## Key Pitfalls

1. **Never modify source directly** — always work on a staging copy
2. **Symlinks**: Preserve them, never follow them, never chmod/sed them
3. **`**` in .distignore** ≠ literal path — it means "any depth"
4. **Permission normalization order**: Detect shebang/executable BEFORE chmod
5. **`--sort=name`** makes the archive deterministic — without it, entry order depends on filesystem
6. **`--single-thread`** makes zstd output deterministic
7. **`file --mime-encoding -b`** is the reliable text/binary detector
8. **The `@` prefix** in `--mtime="@EPOCH"` is required for GNU tar to interpret as epoch seconds
9. **Long filenames**: GNU tar format handles them natively (no special flags needed)
10. **Special characters**: Use `find -print0` and `read -d ''` for safety
11. **zstd overwrite**: Use `-f` flag to overwrite existing output files

## Verification

Verify bit-for-bit reproducibility:
```bash
./build.sh
HASH1=$(sha256sum release.tar.zst | cut -d' ' -f1)
./build.sh
HASH2=$(sha256sum release.tar.zst | cut -d' ' -f1)
[ "$HASH1" = "$HASH2" ] && echo "✓ Deterministic" || echo "✗ Non-deterministic"
```

Verify SOURCE_DATE_EPOCH handling:
```bash
SOURCE_DATE_EPOCH=1609459200 ./build.sh
tar -tvf release.tar.zst --zstd | head -3
# Should show 2021-01-01 00:00 (not 2000-01-01)
```

## Variations

This skill adapts to:
- Different exclusion rule syntaxes (adjust parser)
- Different permission schemes (adjust chmod logic)
- Different text/binary detection methods (adjust `file` command or fallback)
- Different compression levels or algorithms (adjust zstd flags)
- Different tar formats (adjust `--format` flag)
- Different archive root layouts (adjust `-C` and path arguments)

The core pattern (staging → exclude → normalize → deterministic tar → compress) remains constant.
