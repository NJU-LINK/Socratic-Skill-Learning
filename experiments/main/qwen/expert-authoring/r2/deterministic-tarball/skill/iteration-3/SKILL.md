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

## Solver Workflow

Follow these steps in order. Do not skip the parameter extraction step.

```
1. Read task.yaml — extract ALL parameters from the table below
2. Read scripts/build-reference.sh — understand the full implementation
3. Adapt the configuration block — change ONLY the values that differ from defaults
4. Write the adapted script to /app/build.sh and chmod +x
5. Run build.sh once to verify it succeeds
6. Run build.sh a second time and compare SHA-256 hashes (reproducibility check)
```

**Do not explore the source tree in detail** — the reference script handles all
file types, symlinks, special characters, and deep nesting generically. The only
information you need from the task statement is the parameter table below.

---

## Parameter Extraction

Before writing any code, extract these parameters from the task statement.
Every value may differ between variants — always check, never assume defaults.

| Parameter | Typical default | Where to find it in task.yaml |
|---|---|---|
| `SRC_DIR` | `/app/src` | "source tree already exists at …" |
| `OUTPUT` | `/app/release.tar.zst` | "produces …" |
| `IGNORE_FILE` | `.distignore` | "Read exclusion rules from …" |
| `SENSITIVE_MODE` | `0600` | "exclude any file whose mode is exactly …" |
| `DIR_MODE` | `0755` | "directories: …" |
| `EXEC_MODE` | `0755` | "files with a shebang or execute permission: …" |
| `FILE_MODE` | `0644` | "all other regular files: …" |
| Line-ending target | LF | "Normalize line endings to …" |
| `EPOCH` default | `946684800` | "otherwise …" (fallback when SOURCE_DATE_EPOCH unset) |
| Tar `--format` | `gnu` | "Use … tar format" |
| Compressor flags | `zstd -19 --long --no-check --single-thread` | "Compress with `…`" |
| Script path | `/app/build.sh` | "Create … that produces …" |

---

## Adaptation Example

If the task says *"Read exclusion rules from /app/src/.tarignore"*,
*"exclude any file whose mode is exactly 0400"*, and *"directories: 0700"*,
change these lines in the configuration block:

```bash
# Default (from reference script):
IGNORE_FILE="${IGNORE_FILE:-.distignore}"
SENSITIVE_MODE="${SENSITIVE_MODE:-0600}"
DIR_MODE=0755

# Adapted for this variant:
IGNORE_FILE="${IGNORE_FILE:-.tarignore}"
SENSITIVE_MODE="${SENSITIVE_MODE:-0400}"
DIR_MODE=0700
```

If the compressor changes (e.g., to `gzip -9`), replace the entire Step 7
pipeline:

```bash
# Default:
... | zstd -19 --long --no-check --single-thread -o "$OUTPUT"

# Adapted for gzip:
... | gzip -9 > "$OUTPUT"
```

If the tar format changes to `posix`, change `--format=gnu` to `--format=posix`
and add `--pax-option=exthdr.name=%d/PaxHeaders/%f,delete=atime,delete=ctime`
if needed for determinism.

**Key principle:** Only the configuration block (Steps 1–7 headers) and the
compressor/format flags need adaptation. The ignore-file parser, permission
normalizer, line-ending converter, and pipeline structure stay the same.

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
| `name/` (trailing `/`, no inner `/`) | Directory anywhere by name | `find -type d -name "name" -prune -exec rm -rf {} +` |
| `path/to/dir/` (trailing `/`, has inner `/`) | Root-relative directory | `rm -rf "$STAGING/path/to/dir"` |
| `**/name/` | Directory anywhere (explicit) | Same as bare `name/` |
| `*.ext` (bare glob, no `/`) | File glob anywhere | `find -not -type d -name "*.ext" -delete` |
| `**/*.ext` | Same as bare glob | Same as `*.ext` |
| `path/file` (has `/`, no trailing `/`) | Root-relative file | `rm -f` + `find -path` for globs |

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
stdin (pipe), it refuses to overwrite an existing file. Using `rm -f` keeps the
compressor flags exactly as specified (some tests verify exact flag lists).

```bash
rm -f "$OUTPUT"   # ← prevents "already exists" error on re-run

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
   tar pipe. Iteration 1 discovered this: a second `build.sh` invocation failed
   because zstd refused to overwrite when reading from stdin.
2. **Copying reference script without adapting parameters.** The defaults
   match v01, but other variants have different ignore-file names, permission
   targets, or compression flags. Always extract parameters from the task.
3. **Applying dos2unix to binary files.** Use MIME-based detection, not
   filename extensions.
4. **Forgetting `LC_ALL=C`.** Sort order varies by locale, breaking
   reproducibility.
5. **Not handling filenames with spaces/special chars.** Use `-print0` /
   `read -d ''` everywhere.
6. **Dereferencing symlinks.** Never pass `-h` to `cp` or `tar`. Use `cp -a`.
7. **Empty directories after exclusions.** Clean with
   `find -depth -empty -delete`.
8. **Checking shebang on empty files.** Guard with `[[ -s "$f" ]]`.
9. **Staging directory permissions.** `mktemp -d` creates mode `0700`; reset
   to `0755` so the root directory entry has the correct mode.

---

## Self-Verification

After building, verify without modifying the output. Note: `xxd` is typically
**not available** in these environments — use `od` for hex dumps.

```bash
# 1. Archive exists and is non-empty
[[ -s "$OUTPUT" ]]

# 2. List contents with metadata
zstd -d "$OUTPUT" -c | tar -tvf -

# 3. Confirm excluded paths are absent (adapt pattern to variant)
zstd -d "$OUTPUT" -c | tar -tf - | grep -E '(excluded_pattern)' || echo CLEAN

# 4. Check line endings on a known CRLF file (if variant has one)
zstd -d "$OUTPUT" -c | tar -xOf - ./path/to/file | od -A x -t x1z | head

# 5. Reproducibility — run twice, compare hashes
sha256sum "$OUTPUT"
bash /app/build.sh
sha256sum "$OUTPUT"
# Hashes must be identical
```

---

## Reference Implementation

A complete, tested script is at `scripts/build-reference.sh`. It implements
all six pipeline steps with parameterized configuration at the top.

**Usage:** Read the reference script, extract parameters from the task
statement using the table above, change only the configuration values that
differ from defaults, write the result to `/app/build.sh`, and `chmod +x`.
