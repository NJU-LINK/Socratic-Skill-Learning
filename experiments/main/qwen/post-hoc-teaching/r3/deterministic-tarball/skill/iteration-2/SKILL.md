---
name: deterministic-tarball
description: >
  Build a bit-for-bit reproducible compressed tar archive from a source tree.
  Handles exclusion rules from ignore files, permission-based filtering,
  content normalization (line endings for text files), metadata normalization
  (permissions, mtimes, ownership), deterministic entry ordering, and
  reproducible compression. Produces identical output for identical inputs
  regardless of when or where the build runs.
---

# Deterministic Tarball Packaging

## Overview

This skill creates a build script (`build.sh`) that produces a deterministic
`release.tar.zst` (or similar) archive from a source tree. The archive is
bit-for-bit reproducible: same inputs → same byte-identical output, regardless
of build time, filesystem metadata, or host environment.

**Build script re-runnability**: The build script must be safely re-runnable.
It should overwrite existing output files without error. This is critical for
test harnesses that call the build script multiple times, and for development
workflows where developers run builds repeatedly. Compression tools like `zstd`,
`gzip`, and `xz` refuse to overwrite existing files by default when reading
from stdin — always use their `--force` (`-f`) flag.

## Core Methodology

The approach has four phases:

### Phase 0: Environment Hygiene (Mandatory)

Before any processing, lock down environment variables that affect sorting,
localization, and time interpretation. These must be set at the very top of
`build.sh`, right after `set -euo pipefail`:

```bash
export LC_ALL=C
export TZ=UTC
```

- **`LC_ALL=C`**: Forces byte-order sorting in Python's `sorted()`, shell
  comparisons, and any tool that respects locale. Without this, different
  host locales can produce different orderings for paths containing special
  characters or non-ASCII bytes, breaking deterministic entry order.
- **`TZ=UTC`**: Ensures any calendar-style timestamp interpretation is
  consistent. While epoch-based mtimes are timezone-independent, this guards
  against tools or debug output that use calendar conversions.

### Phase 1: Staging Area Construction

Create a temporary staging directory that mirrors the source tree with all
normalizations applied. This isolates the archive content from source-tree
side effects.

```bash
STAGING=$(mktemp -d)
chmod 0755 "$STAGING"   # mktemp defaults to 0700; must normalize
```

### Phase 2: Exclusion Filtering

Apply two layers of exclusion:

1. **Ignore-file patterns**: Parse the project's ignore file (e.g., `.distignore`,
   `.gitignore`, `.npmignore`) and translate its patterns into exclusion rules.
   Common pattern types:
   - `dirname/` — exclude directory and all contents (match any path component)
   - `path/to/dir/` — exclude specific subdirectory path prefix
   - `**/pattern/` — exclude matching directory at any depth
   - `*.ext` — exclude files matching glob pattern
   - `**/*.ext` — exclude matching files at any depth

2. **Permission-based exclusion**: Exclude files whose mode matches a forbidden
   pattern (e.g., exactly `0600` for sensitive files). Check with
   `stat.S_IMODE(st.st_mode) == 0o600`.

**Implementation**: Use Python's `os.walk()` with in-place `dirnames[:]` filtering
to prune excluded directories before descent. For each file, check both ignore
patterns and permission rules before copying.

### Phase 3: Content and Metadata Normalization

For each included entry in the staging area:

**Content normalization:**
- **Text files** (detected by absence of null bytes in the **entire** file):
  convert CRLF → LF
  ```python
  content = content.replace(b'\r\n', b'\n')
  ```
- **Binary files** (containing null bytes anywhere): copy unchanged
- **Symlinks**: preserve as symlinks via `os.readlink()` + `os.symlink()`; do NOT follow

**Text vs binary detection — MUST read the entire file**:

```python
# Single read for both detection and conversion — no partial-read risk
with open(src_path, 'rb') as f:
    content = f.read()

is_text = b'\x00' not in content
if is_text:
    content = content.replace(b'\r\n', b'\n')

with open(dst_path, 'wb') as f:
    f.write(content)
```

**Why full-file detection is critical**: A 64KB-chunk heuristic can
misclassify large binary files (e.g., compiled assets, compressed blobs,
embedded images) where null bytes appear only after the first 64KB. This
would silently apply CRLF→LF conversion to binary data, corrupting it.
Since the file must be read in full anyway for copying, there is no
performance benefit to partial detection.

**Permission normalization:**
- Directories: set to `0755`
- Files with shebang (`#!` as first 2 bytes) OR any execute bit set: `0755`
- All other regular files: `0644`

**Timestamp normalization:**
- Set all entries' mtime to `SOURCE_DATE_EPOCH` env var, or a fixed default
  (commonly `946684800` = 2000-01-01T00:00:00Z)
- Apply via `os.utime(path, (epoch, epoch))`
- For symlinks, use `follow_symlinks=False` (with try/except for portability)

### Phase 4: Deterministic Archive Creation

Use GNU tar with flags that eliminate all sources of non-determinism:

```bash
cd "$STAGING"
tar \
    --create \
    --file=- \
    --format=gnu \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    --mtime="@${EPOCH}" \
    --sort=name \
    --no-acls \
    --no-selinux \
    --no-xattrs \
    . \
  | zstd -19 --long --no-check --single-thread --force -o "$OUTPUT"
```

Key flags and their purposes:

| Flag | Purpose |
|------|---------|
| `--format=gnu` | Fixed tar format (no PAX extended headers with variable content) |
| `--owner=0 --group=0 --numeric-owner` | Eliminate host user/group identity |
| `--mtime="@${EPOCH}"` | Override all entry timestamps in archive headers |
| `--sort=name` | Deterministic entry ordering by path name |
| `--file=-` | Write to stdout for piping to compressor |
| `--no-acls` | Exclude POSIX ACLs (host-specific metadata) |
| `--no-selinux` | Exclude SELinux context labels (host-specific metadata) |
| `--no-xattrs` | Exclude extended attributes (host-specific metadata) |

**Compressor flags for zstd:**

| Flag | Purpose |
|------|---------|
| `-19` | Maximum compression level |
| `--long` | Enable long-range mode for consistent compression context |
| `--no-check` | Remove content checksum (avoids metadata variation) |
| `--single-thread` | Eliminate thread-scheduling non-determinism |
| `--force` | **CRITICAL**: Allow overwriting existing output files. Without this, zstd refuses to overwrite when reading from stdin, breaking re-runnability. |

The `--no-acls`, `--no-selinux`, and `--no-xattrs` flags are no-ops on systems
without these features, so they are safe to always include. They prevent
host-specific filesystem metadata from leaking into the archive and breaking
reproducibility across different build environments.

**Compression determinism**: The compressor must produce identical output for
identical input. For zstd:
- `--single-thread`: Eliminates thread-scheduling non-determinism
- `--no-check`: Removes content checksum (avoids any metadata variation)
- `--long`: Enables long-range mode (consistent compression context)
- Fixed compression level (e.g., `-19`)
- `--force`: **CRITICAL for re-runnability** — allows overwriting existing output files. Without this flag, zstd refuses to overwrite when reading from stdin, causing build failures on subsequent runs.

For gzip, use `gzip -n -f` (no name/timestamp in header, force overwrite). For xz, use `xz -f` (force overwrite) with a fixed compression level.

## Pattern Matching for Ignore Files

The ignore-file pattern language (similar to `.gitignore`) requires careful
translation. Key rules:

```python
import fnmatch

def is_excluded(relpath, is_dir, patterns):
    relpath = relpath.replace(os.sep, '/')
    basename = os.path.basename(relpath)
    parts = relpath.split('/')

    for pat in patterns:
        # ★ MUST check **/ prefix FIRST — before checking trailing /
        if pat.startswith('**/'):
            inner = pat[3:]
            if inner.endswith('/'):
                # Directory at any depth: **/__pycache__/
                inner_dir = inner.rstrip('/')
                if inner_dir in parts:
                    return True
            else:
                # File at any depth: **/*.ext
                if fnmatch.fnmatch(basename, inner):
                    return True
        elif pat.endswith('/'):
            # Directory-only pattern (without **/ prefix)
            dir_pat = pat.rstrip('/')
            if '/' in dir_pat:
                # Multi-component: match as path prefix
                if relpath == dir_pat or relpath.startswith(dir_pat + '/'):
                    return True
            else:
                # Single component: match any path segment
                if dir_pat in parts:
                    return True
        else:
            # Simple glob: match against basename
            if fnmatch.fnmatch(basename, pat):
                return True
    return False
```

**Important edge cases:**
- Patterns like `.hg/` should match `.hg` as any path component (not just root)
- Patterns like `vendor/js/` should match the specific path `vendor/js`
- Patterns like `**/__pycache__/` should match `__pycache__` at any depth
- Patterns like `*.tmp` should match any file ending in `.tmp`
- Filenames with spaces, `$`, `!`, and other special characters must be handled
- **Pattern matching precedence**: When a pattern has both a `**/` prefix and a trailing `/` (e.g., `**/__pycache__/`), check the `**/` prefix **first**. Checking `endswith('/')` first would incorrectly treat `**/__pycache__` as a single-component directory name, which never matches any real path component.

## Symlink Handling

Symlinks must be preserved as symlinks in the archive (not dereferenced):
- Read the link target with `os.readlink(src_path)`
- Recreate in staging with `os.symlink(target, dst_path)`
- GNU tar preserves symlinks by default (does not follow them)
- Symlink timestamps: set with `os.utime(path, times, follow_symlinks=False)`
  (wrap in try/except for portability)

## Long Paths and Special Characters

GNU tar handles long paths natively. The `--format=gnu` supports paths up to
effectively unlimited length. Special characters in filenames (spaces, `$`, `!`,
backslashes) are handled correctly by tar when entries are added via directory
recursion rather than explicit file lists.

## Reproducibility Verification

To verify bit-for-bit reproducibility:
```bash
# Build twice and compare checksums
bash build.sh
HASH1=$(sha256sum release.tar.zst | awk '{print $1}')
rm release.tar.zst
bash build.sh
HASH2=$(sha256sum release.tar.zst | awk '{print $1}')
[ "$HASH1" = "$HASH2" ] && echo "REPRODUCIBLE" || echo "NOT REPRODUCIBLE"
```

## Template build.sh Structure

```bash
#!/bin/bash
set -euo pipefail

# Phase 0: Environment hygiene
export LC_ALL=C
export TZ=UTC

SRC="<source_tree_path>"
OUT="<output_archive_path>"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

EPOCH="${SOURCE_DATE_EPOCH:-<default_epoch>}"
chmod 0755 "$STAGING"
export STAGING EPOCH SRC

# Phase 1-3: Build staging area with Python
python3 << 'PYEOF'
import os, stat, shutil, fnmatch

SRC = os.environ["SRC"]
STAGING = os.environ["STAGING"]
EPOCH = int(os.environ["EPOCH"])

# Read ignore file, walk tree, filter, normalize, copy to staging
# Key: read full file content for text/binary detection (no partial reads)
# Key: single-pass read + convert + write for each file
PYEOF

# Phase 4: Create deterministic archive
cd "$STAGING"
tar --create --file=- --format=gnu \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@${EPOCH}" --sort=name \
    --no-acls --no-selinux --no-xattrs \
    . \
  | <compressor_command> --force -o "$OUT"
```

## Adaptation Guide for Variants

When the task parameters change:

| Variation | What to change |
|-----------|---------------|
| Different ignore file name/format | Update the file path and pattern parser |
| Different forbidden permission | Change the `0o600` check to the required mode |
| Different permission rules | Adjust the permission normalization logic |
| Different line ending target | Change `b'\r\n' → b'\n'` to the required conversion |
| Different epoch source | Change the `SOURCE_DATE_EPOCH` default value |
| Different owner/group | Change `--owner=0 --group=0` values |
| Different tar format | Change `--format=gnu` to `--format=posix` or `--format=ustar` |
| Different compressor | Replace the `zstd` pipeline with `gzip -n`, `xz`, etc. |
| Different output path | Change the `OUT` variable |
