---
name: deterministic-tarball
description: >
  Build bit-for-bit reproducible release archives from a project source tree.
  Covers reading gitignore-style .distignore exclusion files, normalizing
  permissions/line-endings/timestamps/ownership, preserving symlinks, and
  producing deterministic tar+zstd bundles.
---

# Deterministic Release Packaging

## Problem Overview

Given a source tree at a known path (typically `/app/src`) containing mixed
content — source code, generated artifacts, VCS metadata, vendored
dependencies, secrets, symlinks, deeply nested paths, and files with special
characters — produce an executable build script that creates a compressed
archive (typically `/app/release.tar.zst`) that is **bit-for-bit reproducible**
for the same `SOURCE_DATE_EPOCH`.

The script must be created at a specified path (typically `/app/build.sh`) and
must be executable.

## Task Decomposition

Break the problem into six sequential stages. Each stage has clear invariants
that hold across all variants.

### Stage 1 — Discover and Parse Exclusion Rules

**Invariant:** A `.distignore` file lives at the root of the source tree and
uses gitignore-style pattern syntax.

**Strategy:**
- Read `.distignore` line by line; blank lines and `#` comments are ignored.
- Patterns follow gitignore semantics:
  - `dir/` matches a directory and everything beneath it.
  - `*.ext` matches files by extension anywhere in the tree.
  - `**/pattern/` matches a directory name at any depth.
  - A pattern without a slash is matched against the filename component.
  - A pattern with a slash (but not trailing only) is matched from the root.

**Robust implementation — use git:**
The most reliable way to honor gitignore-style patterns in a shell script is to
let git do the matching:

```bash
# In a temporary copy of the source tree (or the tree itself if safe):
git init -q
cp .distignore .gitignore
# --dry-run lists what would be added; respects .gitignore
git add -A --dry-run . 2>/dev/null \
  | sed "s/^add '//;s/'$//" \
  | grep -v '^\.gitignore$'
```

This produces a list of included paths (files and symlinks, NOT directories).
Handle filenames with spaces/special chars by processing one line at a time,
not via word-splitting loops.

**Fallback — manual pattern matching:**
If git is unavailable, use Python's `fnmatch` module or implement the matching
in bash. Parse each pattern, determine if it is a directory pattern (trailing
`/`), a glob (`*`, `?`, `[]`), or a literal, then filter `find` output.

### Stage 2 — Apply Additional Exclusions (Sensitive Files)

**Invariant:** Files with mode `0600` must be excluded from the archive
regardless of whether they appear in `.distignore`.

**Strategy:**
After obtaining the inclusion list from Stage 1, filter out any path whose
permission mode is exactly `0600`:

```bash
# stat format %a gives octal permissions
stat -c '%a' "$srcdir/$path"  # outputs "600" for 0600 files
```

Also exclude any *additional* patterns the task specifies (e.g., files matching
a sensitive-file rule, or paths listed in a secondary ignore file).

### Stage 3 — Stage and Normalize

Create a temporary staging directory that will become the archive root. Copy
only included entries into it, applying normalizations.

#### 3a. Directory structure
For every included file/symlink, ensure all parent directories exist in the
staging area. Set directory permissions to `0755`.

#### 3b. Permission normalization
Apply these rules in order (first match wins):
1. **Directories** → `0755`
2. **Symlinks** → leave as-is (permissions on symlinks are irrelevant on Linux)
3. **Files with a shebang line** (first two bytes `#!`) → `0755`
4. **Files that already have any execute bit set** → `0755`
5. **All other regular files** → `0644`

Detect shebang with: `head -c 2 "$file" | grep -q '^#!'`

#### 3c. Line-ending normalization (text files only)
**Text vs binary detection:**
Use the `file` command. If output contains the word `text` (case-insensitive),
treat it as text. Everything else (including `data`, `image`, `executable`,
ELF, PNG, etc.) is binary.

For text files, convert CRLF → LF:
```bash
sed -i 's/\r$//' "$staged_file"
# or: tr -d '\r' < "$src" > "$dst"
```

**Do NOT modify binary files.** Even if they contain `\r\n` sequences.

Empty files (0 bytes) are safe to treat as text — no content to modify.

#### 3d. Timestamp normalization
Set mtime of every staged entry (files, directories, symlinks) to:
- `$SOURCE_DATE_EPOCH` if that environment variable is set and non-empty
- Otherwise the fallback epoch specified in the task (commonly `946684800`,
  which is 2000-01-01T00:00:00Z)

```bash
epoch="${SOURCE_DATE_EPOCH:-946684800}"
# touch -h for symlinks (don't follow), -d with @epoch
find "$staging" -exec touch -h -d "@$epoch" {} +
```

#### 3e. Ownership normalization
Archive entries must have owner `0` and group `0` (root:root). This is
typically set via tar flags rather than chown on the staging filesystem:
```bash
tar --owner=0 --group=0 --numeric-owner
```

### Stage 4 — Create the Deterministic Tar Archive

**Required tar options:**

| Flag | Purpose |
|------|---------|
| `--format=gnu` | GNU tar format (handles long names, POSIX compatibility) |
| `--sort=name` | Deterministic entry ordering |
| `--owner=0 --group=0 --numeric-owner` | Normalize ownership |
| `--mtime="@$epoch"` | Normalize timestamps at archive level |
| `--no-recursion` | When using `--files-from` to avoid duplicates |
| `-h` / `--dereference` | **Do NOT use** — symlinks must be preserved |

**Approach — tar from staging directory:**
```bash
cd "$staging"
# Find all entries, sort, feed to tar
find . -print0 | LC_ALL=C sort -z | \
  tar --create \
      --file="$output_tar" \
      --format=gnu \
      --sort=name \
      --owner=0 --group=0 --numeric-owner \
      --mtime="@$epoch" \
      --no-recursion \
      --null --files-from=-
```

**Critical detail:** Use `LC_ALL=C` for sort to ensure locale-independent
byte-order sorting. Use `--null` / `-print0` for NUL-delimited paths to handle
spaces and special characters.

### Stage 5 — Compress

Use the exact compression command specified in the task. The default is:
```bash
zstd -19 --long --no-check --single-thread -f "$output_tar" -o "$output_tar.zst"
```

Flags explained:
- `-19`: Maximum compression level
- `--long`: Long-range mode for better compression
- `--no-check`: Disable content checksum (required for bit-for-bit reproducibility)
- `--single-thread`: Single-threaded mode (multi-threading is non-deterministic)
- `-f`: Force overwrite

Remove the intermediate `.tar` after compression.

### Stage 6 — Verification

After building, verify:
1. Output file exists and is non-empty.
2. Decompress and list contents: `zstd -d "$output" --stdout | tar -t`
3. Confirm excluded paths are absent.
4. Confirm 0600 files are absent.
5. Confirm symlinks are stored as symlinks (shown as `-> target` in `tar -tv`).
6. Confirm permissions match expected normalized values.
7. **Reproducibility check:** Run the entire build again with the same
   `SOURCE_DATE_EPOCH` and compare checksums: `sha256sum "$output"`.

## Common Pitfalls

1. **Word-splitting on filenames with spaces:** Always use NUL-delimited I/O
   (`-print0`, `--null`, `while IFS= read -r -d '' line`).
2. **Following symlinks:** Never use `cp -L`, `tar -h`, or `find -L` when
   collecting archive content. Use `cp -a` or `cp -d` to preserve symlinks.
3. **Locale-dependent sort order:** Always prefix `sort` with `LC_ALL=C`.
4. **Treating binary files as text:** Always detect file type before line-ending
   conversion. Converting a PNG's `\r\n` byte sequences will corrupt it.
5. **Including the staging `.gitignore`:** When using the git-based approach,
   exclude `.gitignore` from the file list (it's a temp artifact).
6. **Empty directories:** `git add --dry-run` only lists files/symlinks. You
   must infer and create parent directories in the staging area.
7. **mtime on symlinks:** Use `touch -h` to avoid following the symlink.
8. **Non-deterministic zstd:** Omitting `--single-thread` or `--no-check` will
   produce different output across runs.

## Variant Dimensions

### source_tree_content_and_exclusions
- Different directory names, file extensions, symlink targets
- Different `.distignore` patterns (more/fewer rules, nested globs, negations)
- Different sensitive-file rules (mode-based, name-based, or both)
- Different scale (more files, deeper nesting, longer names)

**Adaptation:** The git-based exclusion approach handles arbitrary gitignore
patterns. The 0600 check is a simple stat filter. Both generalize without
changes.

### normalization_rules
- Different permission mappings (e.g., different execute-bit rules)
- Different timestamp sources (commit time, changelog date, fixed epoch)
- Different text-file detection heuristics
- Different line-ending requirements (LF, CRLF, or no normalization)
- Different owner/group policy

**Adaptation:** Each normalization is a configurable parameter. Read the task
spec carefully for the exact rules and substitute them into the staging stage.

### archive_format_and_compression
- Different tar format (pax, ustar, gnu)
- Different compression (gzip, xz, zstd with different levels)
- Different output path
- Different environment variable names for the epoch
- Additional verification (checksums, signatures)

**Adaptation:** Swap tar `--format` flag and compression command. The
deterministic principles (sorted, fixed mtime/owner, single-threaded
compression) remain the same.

## Reference Implementation Pattern

```bash
#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="/app/src"
OUTPUT="/app/release.tar.zst"
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

# --- Stage 1: Get included files via git ---
WORK="$(mktemp -d)"
cp -a "$SRC_DIR/." "$WORK/"
cd "$WORK"
git init -q
cp .distignore .gitignore

FILE_LIST="$(mktemp)"
git add -A --dry-run . 2>/dev/null \
  | sed "s/^add '//;s/'$//" \
  | grep -v '^\.gitignore$' \
  > "$FILE_LIST"

# --- Stage 2: Filter out 0600 files ---
FILTERED="$(mktemp)"
while IFS= read -r relpath; do
    full="$WORK/$relpath"
    if [ -L "$full" ]; then
        echo "$relpath" >> "$FILTERED"       # symlinks: always include
    elif [ -f "$full" ]; then
        mode="$(stat -c '%a' "$full")"
        [ "$mode" != "600" ] && echo "$relpath" >> "$FILTERED"
    fi
done < "$FILE_LIST"

# --- Stage 3: Stage and normalize ---
mkdir -p "$STAGING"

while IFS= read -r relpath; do
    src="$WORK/$relpath"
    dst="$STAGING/$relpath"
    mkdir -p "$(dirname "$dst")"

    if [ -L "$src" ]; then
        # Preserve symlink
        target="$(readlink "$src")"
        ln -s "$target" "$dst"
    else
        cp "$src" "$dst"

        # Permission normalization
        if head -c 2 "$dst" 2>/dev/null | grep -q '^#!'; then
            chmod 0755 "$dst"
        elif [ -x "$src" ]; then
            chmod 0755 "$dst"
        else
            chmod 0644 "$dst"
        fi

        # Line-ending normalization (text files only)
        ftype="$(file -b "$dst" 2>/dev/null)"
        if echo "$ftype" | grep -qi 'text'; then
            sed -i 's/\r$//' "$dst"
        fi
    fi
done < "$FILTERED"

# Ensure all directories are 0755
find "$STAGING" -type d -exec chmod 0755 {} +

# Set mtimes
find "$STAGING" -exec touch -h -d "@$EPOCH" {} +

# --- Stage 4: Create tar ---
TAR_FILE="${OUTPUT%.zst}"
cd "$STAGING"
find . -print0 | LC_ALL=C sort -z | \
    tar --create \
        --file="$TAR_FILE" \
        --format=gnu \
        --sort=name \
        --owner=0 --group=0 --numeric-owner \
        --mtime="@$EPOCH" \
        --no-recursion \
        --null --files-from=-

# --- Stage 5: Compress ---
zstd -19 --long --no-check --single-thread -f "$TAR_FILE" -o "$OUTPUT"
rm -f "$TAR_FILE"

# Cleanup
rm -f "$FILE_LIST" "$FILTERED"
rm -rf "$WORK"
```

This pattern is a starting skeleton. Adapt variable names, paths, permission
rules, text-detection logic, and compression flags to match the specific task
variant.
