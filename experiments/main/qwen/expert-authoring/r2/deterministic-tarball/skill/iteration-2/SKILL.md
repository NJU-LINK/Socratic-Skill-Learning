---
name: deterministic-tarball
description: >
  Build deterministic, bit-for-bit reproducible release archives from project
  source trees. Teaches ignore-file parsing, metadata normalization (permissions,
  timestamps, ownership), content normalization (line endings for text vs binary
  detection), symlink preservation, and compressed archive creation with GNU tar
  and zstd.
---

# Deterministic Release Tarball

## Task Analysis Procedure

Before writing any code, extract these **variant parameters** from the task
statement. Every parameter marked ⚙️ may differ between variants.

| Parameter | Typical default | Where to find it |
|---|---|---|
| Source tree path | `/app/src` | "source tree already exists at …" |
| Output path | `/app/release.tar.zst` | "produces …" |
| Ignore-file name | `.distignore` | "Read exclusion rules from …" |
| Sensitive-file mode | `0600` | "exclude any file whose mode is exactly …" |
| Dir permission | `0755` | "directories: …" |
| Exec permission | `0755` | "files with a shebang or execute permission: …" |
| Regular-file permission | `0644` | "all other regular files: …" |
| Line-ending target | LF | "Normalize line endings to …" |
| Epoch default | `946684800` | "otherwise …" |
| Tar format | `gnu` | "Use … tar format" |
| Compressor flags | `zstd -19 --long --no-check --single-thread` | "Compress with …" |
| Script path | `/app/build.sh` | "Create … that produces …" |

After extracting parameters, **adapt the reference script** in
`scripts/build-reference.sh` by replacing its configuration block with the
extracted values. Then write the adapted script to the task's script path and
`chmod +x`.

---

## Core Pipeline

```
Stage → Exclude → Normalize metadata → Normalize content → Archive → Compress
```

Work in a **temporary staging directory** to avoid modifying the source tree:

```bash
STAGING="$(mktemp -d)"
chmod 0755 "$STAGING"
trap 'rm -rf "$STAGING"' EXIT
```

### 1. Stage the Source Tree

```bash
cp -a "$SRC_DIR"/. "$STAGING"/
```

`-a` preserves symlinks without following them. Trailing `/.` copies contents
into staging rather than nesting the source directory itself.

### 2. Apply Ignore-File Exclusions

The ignore file uses a **gitignore-like** format. Parse line-by-line:

| Pattern shape | Meaning | Removal strategy |
|---|---|---|
| `name/` (trailing `/`, no inner `/`) | Directory anywhere by name | `find "$STAGING" -type d -name "name" -prune -exec rm -rf {} +` |
| `path/to/dir/` (trailing `/`, has inner `/`) | Root-relative directory | `rm -rf "$STAGING/path/to/dir"` |
| `**/name/` | Directory anywhere (explicit) | Same as bare `name/` — `find -type d -name` |
| `*.ext` (bare glob, no `/`) | File glob anywhere | `find "$STAGING" -not -type d -name "*.ext" -delete` |
| `**/*.ext` | Same as bare glob | Same as `*.ext` |
| `path/file` (has `/`, no trailing `/`) | Root-relative file | `rm -f "$STAGING/path/file"` + `find -path` for globs |

**Parsing rules:**
- Strip trailing `\r` (handle CRLF ignore files).
- Skip blank lines and `#` comment lines.

After ignore-file removals, exclude **sensitive files by mode**:

```bash
find "$STAGING" -type f -perm "$SENSITIVE_MODE" -delete
```

Then **clean up empty directories** left by exclusions:

```bash
find "$STAGING" -mindepth 1 -depth -type d -empty -delete
```

### 3. Normalize Permissions

**Skip symlinks** — they have no meaningful permissions on most Linux systems.

| Entry type | Condition | Mode |
|---|---|---|
| Directory | — | `$DIR_MODE` |
| Regular file | Starts with `#!` (shebang) **or** has execute bit | `$EXEC_MODE` |
| Regular file | All others | `$FILE_MODE` |

Shebang detection — guard against empty files:

```bash
[[ -s "$f" ]] && head -c 2 "$f" 2>/dev/null | grep -q '^#!'
```

Safe iteration over files with spaces/special characters:

```bash
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do ... done
```

### 4. Normalize Line Endings (Text Files Only)

**Text vs binary** — use MIME type from `file --mime-type -b`:

```bash
mime="$(file --mime-type -b "$f")"
if [[ "$mime" == text/* ]]; then
    dos2unix -q "$f"       # CRLF → LF
fi
```

- `text/*` matches `text/plain`, `text/x-python`, `text/x-c`,
  `text/x-shellscript`, etc.
- Binary types (`image/png`, `application/octet-stream`) are **never** touched.
- Empty files (`inode/x-empty`) are safe — dos2unix on empty is a no-op.
- **Fallback** if `dos2unix` unavailable: `sed -i 's/\r$//' "$f"`

### 5. Deterministic Tar + Compress

**CRITICAL — remove existing output before compression.** When zstd reads from
stdin (pipe), it refuses to overwrite an existing file. This causes the second
run of a reproducibility test to fail silently. Using `rm -f` keeps the
compressor flags exactly as specified (some tests verify exact flag lists).

```bash
rm -f "$OUTPUT"   # ← prevents zstd "already exists" error on re-run

LC_ALL=C tar \
    --sort=name \
    --mtime="@${EPOCH}" \
    --owner=0 --group=0 --numeric-owner \
    --format=gnu \
    -cf - \
    -C "$STAGING" \
    . \
  | zstd -19 --long --no-check --single-thread -o "$OUTPUT"
```

| Flag | Purpose |
|---|---|
| `LC_ALL=C` | Locale-independent sort order |
| `--sort=name` | Lexicographic entry order |
| `--mtime=@EPOCH` | Uniform mtime for all entries |
| `--owner=0 --group=0` | Uniform owner/group |
| `--numeric-owner` | Store numeric UID/GID |
| `--format=gnu` | GNU tar format header |
| `-C "$STAGING" .` | Archive from staging root; entries prefixed `./` |

**Do NOT use `-h` / `--dereference`** — the default preserves symlinks.

---

## Variation Axes

### source_tree_content_and_exclusions

- Directory names, extensions, and file types change between variants.
- The ignore file name may differ — extract from the task statement.
- Sensitive-file rules may target different modes (e.g. `0400`).
- Symlink targets may be relative, absolute, or broken — always preserve as-is.

### normalization_rules

- Permission targets may differ — use variables, not hardcoded modes.
- Timestamp source may be git commit time or changelog date.
- Line-ending requirement may be CRLF instead of LF (rare).
- Text-file detection heuristic may need tuning (e.g. `application/xml`).

### archive_format_and_compression

- Tar format may be `posix` (PAX) instead of `gnu`.
- Compression may be `gzip`, `xz`, or uncompressed — replace the compressor
  pipeline entirely.
- Output path and filename may differ.

---

## Common Pitfalls

1. **zstd "already exists" on re-run.** Always `rm -f "$OUTPUT"` before the
   tar pipe. The solver in iteration 1 discovered this the hard way — a second
   `build.sh` invocation failed because zstd refused to overwrite the output
   when reading from stdin.
2. **Applying dos2unix to binary files.** Use MIME-based detection, not
   filename extensions.
3. **Forgetting `LC_ALL=C`.** Sort order varies by locale, breaking
   reproducibility.
4. **Not handling filenames with spaces/special chars.** Use `-print0` /
   `read -d ''` everywhere.
5. **Dereferencing symlinks.** Never pass `-h` to `cp` or `tar`. Use `cp -a`.
6. **Empty directories after exclusions.** Clean with
   `find -depth -empty -delete`.
7. **Checking shebang on empty files.** Guard with `[[ -s "$f" ]]`.
8. **Staging directory permissions.** `mktemp -d` creates mode `0700`; reset
   to `0755` so the root directory entry has the correct mode.
9. **Modifying the source tree in-place.** Always use a staging directory.

---

## Self-Verification

After building, verify without modifying the output:

```bash
# 1. Archive exists and is non-empty
[[ -s "$OUTPUT" ]]

# 2. List contents with metadata
zstd -d "$OUTPUT" -c | tar -tvf -

# 3. Confirm excluded paths are absent (adapt pattern to variant)
zstd -d "$OUTPUT" -c | tar -tf - | grep -E '(excluded_pattern)' || echo CLEAN

# 4. Reproducibility — run twice, compare hashes
sha256sum "$OUTPUT"
bash /app/build.sh
sha256sum "$OUTPUT"
# Hashes must be identical
```

---

## Reference Implementation

A complete, tested script is at `scripts/build-reference.sh`. It implements
all six pipeline steps with parameterized configuration at the top. Adapt the
configuration block to match the variant's task parameters, copy to the
script path, and `chmod +x`.
