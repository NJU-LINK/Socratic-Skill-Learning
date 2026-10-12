---
name: deterministic-tarball
description: >
  Build a bit-for-bit reproducible release archive from a source tree by applying
  exclusion rules (.distignore), removing sensitive files (0600 mode), normalizing
  permissions and line endings, and creating a deterministic tar.zst archive.
---

# Deterministic Tarball Packaging

## Architecture: Staging-Directory Pipeline

Never modify the source tree in place. The pipeline is:

```
SOURCE → COPY → EXCLUDE → CLEAN → NORMALIZE → ARCHIVE
```

1. **Copy** the source tree to a temporary staging directory using `cp -a` (preserves symlinks as symlinks; do NOT use `-h`/`--dereference`).
2. **Exclude** files matching `.distignore` patterns and 0600-mode files.
3. **Clean** empty directories left behind by exclusions.
4. **Normalize** permissions and line endings on the staging copy.
5. **Archive** with deterministic tar flags piped to zstd.

## .distignore Pattern Translation

The `.distignore` file uses gitignore-like patterns. Translation rules:

| Pattern | Meaning | Action |
|---------|---------|--------|
| `dir/` | Rooted directory | `rm -rf "$STAGING/dir"` |
| `path/to/dir/` | Rooted nested path | `rm -rf "$STAGING/path/to/dir"` |
| `**/pattern/` | Directory at any depth | `find "$STAGING" -mindepth 1 -type d -name "pattern" -exec rm -rf {} +` |
| `*.ext` | File glob at any depth | `find "$STAGING" -mindepth 1 -name "*.ext" -delete` |
| `**/pattern` | Any-depth match | `find "$STAGING" -mindepth 1 -name "pattern" -delete` |

Strip trailing `/` for directory detection, strip leading `**/` for depth-anchoring.

**Important**: Handle CRLF line endings in `.distignore` itself. When reading patterns, strip trailing `\r`:
```bash
while IFS= read -r pattern || [ -n "$pattern" ]; do
    pattern="${pattern%$'\r'}"  # Strip trailing CR if present
    [ -z "$pattern" ] && continue
    [[ "$pattern" == \#* ]] && continue
    # ... rest of pattern processing
done < "$DISTIGNORE"
```

## 0600 Exclusion

```bash
find "$STAGING" -type f -perm 0600 -delete
```

This runs AFTER copying but BEFORE permission normalization. Files with mode exactly 0600 are always excluded regardless of `.distignore`.

## Empty Directory Cleanup

After all exclusions, remove directories that became empty:

```bash
find "$STAGING" -mindepth 1 -depth -type d -empty -delete
```

The `-depth` flag processes children before parents so nested empty directories cascade correctly.

## Permission Normalization

Apply to the staging copy only:

- **Directories** → `0755`
- **Files with shebang** (`head -c2` starts with `#!`) → `0755`
- **Files with execute bit** (`[ -x "$f" ]`) → `0755`
- **All other regular files** → `0644`
- **Symlinks** → skip (permissions not stored in tar)

Capture shebang and execute status BEFORE any file modification.

**CRITICAL**: Use null-delimited processing (`find -print0 | while read -d ''`) to handle filenames with newlines, spaces, and other special characters. Do NOT use `find | while read` — this will break on filenames containing newlines.

```bash
find "$STAGING" -mindepth 1 -print0 | while IFS= read -r -d '' entry; do
    # ... process entry
done
```

The normalization loop order does NOT need sorting — tar's `--sort=name` flag handles entry ordering in the final archive.

## Text/Binary Detection and Line Ending Normalization

Use `file --mime-encoding -b "$f"` to detect binary files:

- Returns `binary` for files containing null bytes (detected via content inspection)
- Returns encoding name (e.g., `us-ascii`, `utf-8`) for text files

Only normalize CRLF → LF on text files:

```bash
enc=$(file --mime-encoding -b "$f")
if [ "$enc" != "binary" ]; then
    chmod u+w "$f"    # handle read-only files; sed -i needs write permission
    sed -i 's/\r$//' "$f"
fi
```

Binary files (images, compiled objects, files with null bytes) are left untouched.

## Deterministic Archive Command

```bash
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"
cd "$STAGING"
LC_ALL=C tar --create \
    --file=- \
    --sort=name \
    --format=gnu \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${EPOCH}" \
    . \
    | zstd -19 --long --no-check --single-thread -o "$OUT"
```

### Critical flags and why each matters:

| Flag | Purpose |
|------|---------|
| `LC_ALL=C` | Deterministic byte-order sort regardless of system locale |
| `--sort=name` | GNU tar sorts entries by name for reproducibility |
| `--format=gnu` | GNU tar format (handles long paths via extensions) |
| `--owner=0 --group=0 --numeric-owner` | Numeric 0:0 ownership, no name lookup variance |
| `--mtime="@${EPOCH}"` | Uniform mtime for all entries; uses `SOURCE_DATE_EPOCH` or fallback |
| `.` as root | Entries become `./file.txt`, `./dir/` etc. |
| `zstd -19 --long --no-check --single-thread` | Max compression, long mode, no checksum, single thread for determinism |

### Reproducibility checklist:

- [x] `LC_ALL=C` for locale-independent sort
- [x] `--sort=name` for deterministic entry order
- [x] `--mtime` set uniformly from epoch variable
- [x] `--owner`/`--group` numeric (no name resolution variance)
- [x] `zstd --single-thread` (no thread-count variance)
- [x] `zstd --no-check` (no checksum seed variance)
- [x] No build-process timestamps leak into archive
- [x] `rm -f "$OUT"` before pipeline to allow zstd overwrite

## Key Invariants

1. **Never modify source in place** — always work on a staging copy
2. **Preserve symlinks as symlinks** — use `cp -a`, never `cp -ah` or `--dereference`
3. **Always set `LC_ALL=C`** — locale-independent byte ordering
4. **Always set `--mtime`** — uniform timestamp from `SOURCE_DATE_EPOCH`
5. **Always set `--owner=0 --group=0 --numeric-owner`** — no name resolution
6. **Capture file properties before modification** — shebang/exec status before chmod/sed
7. **Handle read-only files** — `chmod u+w` before `sed -i`
8. **Clean empty directories** — after exclusions, before archiving

## Spec Variation Dimensions

The skill handles variation along three axes:

1. **Source tree content and exclusions** — different directory names, extension patterns, sensitive-file rules, symlink cases, scale
2. **Normalization rules** — different permission rules, timestamp sources, text-file detection, line-ending requirements, owner/group policy
3. **Archive format and compression** — different tar format options, compression level, output path, environment variables, verification hashes

The core pipeline (copy → exclude → clean → normalize → archive) and the deterministic flags remain invariant across variants.

## Efficiency and Best Practices

Based on iteration experience:

1. **Use `od` instead of `xxd`** — `xxd` is not always available; `od -A x -t x1z` provides equivalent hex inspection
2. **Batch exploration commands** — combine multiple `ls`, `find`, `cat` calls into single compound commands to reduce tool call overhead
3. **Read SKILL.md first** — understand the architecture before exploring the source tree
4. **Verify incrementally** — check exclusions, permissions, line endings, and reproducibility in separate focused tests
5. **Handle edge cases** — CRLF in `.distignore`, read-only files, empty directories after exclusions

## Common Pitfalls

1. **Modifying source in place** — always use a staging directory
2. **Forgetting to capture shebang/exec before modification** — check before `chmod` or `sed`
3. **Not handling read-only files** — `chmod u+w` before `sed -i`
4. **Leaving empty directories** — clean up after exclusions with `find -depth -type d -empty -delete`
5. **Using wrong binary detection** — `file --mime-encoding -b` returns `binary` for files with null bytes
6. **Forgetting `LC_ALL=C`** — required for deterministic sort order
7. **Not removing output before pipeline** — `rm -f "$OUT"` before `tar | zstd` to allow overwrite
8. **Using `find | while read` instead of `find -print0 | while read -d ''`** — the former breaks on filenames with newlines; always use null-delimited processing for file iteration
