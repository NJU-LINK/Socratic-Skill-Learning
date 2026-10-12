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

## Problem

Given a project source tree, produce a compressed archive that is **bit-for-bit
reproducible** for the same `SOURCE_DATE_EPOCH`. The archive must:

1. Exclude paths matched by an ignore file (e.g. `.distignore`).
2. Exclude sensitive files identified by permission mode (e.g. `0600`).
3. Normalize permissions, line endings, timestamps, and ownership.
4. Preserve symlinks as symlinks (never dereference).
5. Sort entries deterministically.
6. Compress with deterministic flags.

## Core Pipeline

```
Stage → Exclude → Normalize metadata → Normalize content → Archive → Compress
```

Each step is isolated; the order matters. Work in a **temporary staging
directory** to avoid modifying the source tree. Clean up with a trap:

```bash
STAGING="$(mktemp -d)"
chmod 0755 "$STAGING"
trap 'rm -rf "$STAGING"' EXIT
```

---

## Step-by-Step Decision Rules

### 1. Stage the Source Tree

```bash
cp -a "$SRC_DIR"/. "$STAGING"/
```

`-a` preserves symlinks (both relative and absolute) without following them.
The trailing `/.` copies *contents* into staging rather than nesting the source
directory itself.

### 2. Apply Ignore-File Exclusions

The ignore file uses a **gitignore-like** format. Parse line-by-line:

| Pattern shape | Meaning | Removal strategy |
|---|---|---|
| `dir/` (trailing `/`, no inner `/`) | Directory at root | `rm -rf "$STAGING/dir"` |
| `path/to/dir/` (trailing `/`, has inner `/`) | Root-relative directory path | `rm -rf "$STAGING/path/to/dir"` |
| `**/name/` | Directory name anywhere | `find "$STAGING" -type d -name "name" -prune -exec rm -rf {} +` |
| `*.ext` (bare glob, no `/`) | File glob matched anywhere by name | `find "$STAGING" -not -type d -name "*.ext" -delete` |
| `**/*.ext` | Same as bare glob (recursive by default in find) | `find "$STAGING" -not -type d -name "*.ext" -delete` |
| `path/file` (has `/`, no trailing `/`) | Root-relative file | `rm -f "$STAGING/path/file"` |

**Parsing rules:**

- Strip trailing `\r` (handle CRLF ignore files).
- Skip blank lines and `#` comment lines.
- Process directory patterns **before** file patterns when order matters (the
  reference script processes them in file order, which works because directory
  removal is recursive).

After ignore-file removals, also remove files matching the **sensitive-mode
rule** (e.g. mode exactly `0600`):

```bash
find "$STAGING" -type f -perm 0600 -delete
```

Then clean up directories left empty by exclusions:

```bash
find "$STAGING" -mindepth 1 -depth -type d -empty -delete
```

Use `-depth` so nested empty directories are removed bottom-up in one pass.

### 3. Normalize Permissions

Apply to the staging filesystem. **Skip symlinks** — they do not have
meaningful permissions on most systems.

| Entry type | Condition | Mode |
|---|---|---|
| Directory | — | `0755` |
| Regular file | Starts with `#!` (shebang) **or** has execute bit | `0755` |
| Regular file | All others | `0644` |

**Shebang detection** — only check non-empty files to avoid false positives:

```bash
[[ -s "$f" ]] && head -c 2 "$f" | grep -q '^#!'
```

**Safe iteration** over files with spaces and special characters:

```bash
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do ... done
```

### 4. Normalize Line Endings (Text Files Only)

**Text vs binary detection** — use MIME type from `file`:

```bash
mime="$(file --mime-type -b "$f")"
if [[ "$mime" == text/* ]]; then
    dos2unix -q "$f"
fi
```

- `text/*` matches: `text/plain`, `text/x-python`, `text/x-c`,
  `text/x-shellscript`, etc.
- Binary files (`image/png`, `application/octet-stream`, `inode/x-empty`) are
  **never** touched. This is critical: running dos2unix on a binary file
  corrupts it.
- Empty files (`inode/x-empty`) are safe either way — dos2unix on an empty file
  is a no-op.
- **Fallback** if `dos2unix` is unavailable: `sed -i 's/\r$//' "$f"`

### 5. Create Deterministic Tar

Use `LC_ALL=C` to make sort order locale-independent.

| Flag | Purpose |
|---|---|
| `--sort=name` | Lexicographic entry order (overrides filesystem order) |
| `--mtime="@${EPOCH}"` | Uniform mtime for all entries (seconds since epoch) |
| `--owner=0 --group=0` | Uniform owner/group names and UIDs |
| `--numeric-owner` | Store numeric UID/GID (0:0) |
| `--format=gnu` | GNU tar format header |
| `-cf -` | Write to stdout (pipe to compressor) |
| `-C "$STAGING" .` | Archive from staging root; entries prefixed with `./` |

**Do NOT use `-h` / `--dereference`** — the default (no `-h`) preserves
symlinks as symlinks.

**Epoch fallback**: `"${SOURCE_DATE_EPOCH:-946684800}"` (Y2K fallback when the
environment variable is unset).

### 6. Compress Deterministically

```bash
zstd -19 --long --no-check --single-thread -o "$OUTPUT"
```

| Flag | Purpose |
|---|---|
| `-19` | Maximum compression level |
| `--long` | Enable long-range matching |
| `--no-check` | Omit embedded checksum (aids bit-for-bit reproducibility) |
| `--single-thread` | Eliminate thread-scheduling non-determinism |

---

## Variation Axes

### source_tree_content_and_exclusions

- Directory names, extensions, and file types change between variants.
- The ignore file name may differ (`.distignore`, `.tarignore`, etc.) — read
  the task statement.
- Sensitive-file rules may target different modes or patterns (e.g. `0400`
  instead of `0600`).
- Symlink targets may be relative, absolute, or broken — always preserve
  as-is.

### normalization_rules

- Permission targets may differ (e.g. dirs `0700`, executables `0700`).
- Timestamp source may be a git commit time, a changelog date, or
  `SOURCE_DATE_EPOCH`.
- Owner/group names may need specific strings (e.g. `root` instead of `0`).
- Line-ending requirement may be CRLF instead of LF (rare; check the spec).
- Text-file detection heuristic may need tuning (e.g. including
  `application/xml` as text).

### archive_format_and_compression

- Tar format may be `posix` (PAX) instead of `gnu`.
- Compression may be `gzip`, `xz`, or uncompressed.
- Output path and filename may differ.
- Additional tar flags: `--pax-option` for PAX, `--checkpoint` for progress.
- The archive root layout may change (e.g. entries under `project-name/`
  instead of `./`).

---

## Common Pitfalls

1. **Modifying the source tree in-place.** Always use a staging directory.
2. **Applying dos2unix to binary files.** Use MIME-based detection, not
   filename extensions.
3. **Forgetting `LC_ALL=C`.** Sort order varies by locale, breaking
   reproducibility.
4. **Not handling filenames with spaces/special chars.** Use `-print0` /
   `read -d ''` everywhere.
5. **Dereferencing symlinks.** Never pass `-h` to `cp` or `tar`. Use `cp -a`.
6. **Empty directories after exclusions.** Clean them up with
   `find -depth -empty -delete`.
7. **Checking shebang on empty files.** Guard with `[[ -s "$f" ]]` to avoid
   false matches.
8. **Staging directory permissions.** `mktemp -d` creates mode `0700`; reset to
   `0755` so the root directory entry in the archive has the correct mode.
9. **Tar `--owner=0` vs `--owner=root`.** Both set UID to 0; `--numeric-owner`
   ensures the numeric ID is authoritative. Use `0` for clarity.
10. **Omitting `--single-thread` in zstd.** Multi-threaded compression can
    produce non-deterministic output.

---

## Self-Verification Checklist

After building the archive, verify:

```bash
# 1. Archive exists and is non-empty
[[ -s "$OUTPUT" ]]

# 2. List contents and check sort order
zstd -d "$OUTPUT" -c | tar -tvf - | awk '{print $NF}'

# 3. Confirm excluded paths are absent
zstd -d "$OUTPUT" -c | tar -tf - | grep -E '(\.hg|vendor/js|scratch|__pycache__|\.tmp|\.pyc|\.pyo|\.class|\.o)'
# Should produce no output

# 4. Confirm sensitive files are absent
zstd -d "$OUTPUT" -c | tar -tf - | grep -E '(private\.key|db\.conf)'
# Should produce no output

# 5. Verify reproducibility — run twice, compare hashes
sha256sum "$OUTPUT"
# Run build.sh again, then compare
```

---

## Reference Implementation

A complete, tested `build.sh` is provided at
`scripts/build-reference.sh`. Read it, adapt the configuration variables
at the top (`SRC_DIR`, `OUTPUT`, `IGNORE_FILE`, `EPOCH`), and adjust any
variant-specific rules (permission targets, compression flags, sensitive-file
mode). Copy the adapted script to `/app/build.sh` and `chmod +x /app/build.sh`.
