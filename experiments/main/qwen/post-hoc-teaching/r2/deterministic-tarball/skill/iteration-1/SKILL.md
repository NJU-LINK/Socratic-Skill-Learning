---
name: deterministic-tarball
description: >
  Build bit-for-bit reproducible release archives from a project source tree.
  Reads exclusion rules from an ignore file, excludes sensitive files by
  permission, normalizes metadata (permissions, line endings, mtimes, ownership),
  preserves symlinks, and produces a deterministically sorted and compressed
  archive. Handles long paths, special characters, deep nesting, and mixed
  text/binary content.
---

# Deterministic Tarball Packaging

## Overview

This skill creates a reproducible release archive from an existing project source tree. The output is bit-for-bit identical across runs given the same inputs and configuration. The process has three phases: (1) filter and normalize content into a staging area, (2) create a deterministic tar archive, (3) compress with a deterministic compressor.

## Architecture

```
Source Tree ──► [Filter + Normalize] ──► Staging Dir ──► [tar] ──► [compress] ──► Archive
                     │                       │              │            │
               .distignore              perms, mtimes    --sort=name  zstd -19
               0600 check               line endings     --mtime=     --single-thread
               text/binary              owner/group      --format     --no-check
```

## Phase 1: Filter and Normalize

### 1.1 Exclusion Rules

Read exclusion patterns from the project's ignore file (commonly `.distignore`). Implement gitignore-style pattern matching:

| Pattern Form | Meaning | Example |
|---|---|---|
| `dirname/` | Exclude directory (and contents) by name at any depth | `.hg/`, `scratch/` |
| `path/dir/` | Exclude specific directory path prefix | `vendor/js/` |
| `**/name/` | Exclude directory by name at any depth explicitly | `**/__pycache__/` |
| `*.ext` | Exclude files matching glob by basename | `*.tmp`, `*.pyc`, `*.o` |
| `**/*.ext` | Exclude files matching glob at any depth | `**/*.log` |

**Implementation approach** (Python recommended for robustness):

```python
import fnmatch, os, stat

def is_excluded(rel_path, patterns, is_dir):
    """Check if rel_path should be excluded per ignore patterns."""
    rel_norm = rel_path.replace(os.sep, '/')
    parts = rel_norm.split('/')
    basename = parts[-1]
    
    for pattern in patterns:
        pat = pattern.replace(os.sep, '/')
        
        if pat.endswith('/'):
            dir_name = pat.rstrip('/')
            if dir_name.startswith('**/'):
                target = dir_name[3:]
                check = parts[:-1] if not is_dir else parts
                if any(p == target for p in check):
                    return True
            elif '/' in dir_name:
                if rel_norm == dir_name or rel_norm.startswith(dir_name + '/'):
                    return True
            else:
                if is_dir and basename == dir_name:
                    return True
                if any(p == dir_name for p in parts[:-1]):
                    return True
        else:
            if pat.startswith('**/'):
                if fnmatch.fnmatch(basename, pat[3:]):
                    return True
            elif '/' in pat:
                if fnmatch.fnmatch(rel_norm, pat):
                    return True
            else:
                if fnmatch.fnmatch(basename, pat):
                    return True
    return False
```

Use `os.walk()` with in-place `dirnames` filtering to avoid descending into excluded directories.

### 1.2 Permission-Based Exclusion

Exclude any regular file whose mode is exactly `0600` (owner read-write only), regardless of ignore patterns. Check with:

```python
fmode = stat.S_IMODE(os.lstat(path).st_mode)
if fmode == 0o600:
    continue  # skip this file
```

### 1.3 Text vs Binary Detection

Detect binary files by checking for null bytes (`\x00`) in the file content:

```python
def is_binary(filepath):
    with open(filepath, 'rb') as f:
        return b'\x00' in f.read(8192)
```

This is the same heuristic used by `git` and `file`. It correctly handles:
- PNG images (contain null bytes in IHDR chunk)
- Mixed content files (null bytes → binary, preserved unchanged)
- Pure text files (no null bytes → text, line endings normalized)
- Empty files (no null bytes → text, no-op normalization)

### 1.4 Line Ending Normalization

For text files only, convert CRLF (`\r\n`) to LF (`\n`):

```python
data = data.replace(b'\r\n', b'\n')
```

Binary files are copied byte-for-byte without modification.

### 1.5 Permission Normalization

Apply these rules to regular files in the staging area:

| Condition | Permission |
|---|---|
| Directory | `0755` |
| File has shebang (`#!`) OR any execute bit set | `0755` |
| All other regular files | `0644` |

Shebang detection: check if first 2 bytes are `#!`.
Execute detection: check `mode & (S_IXUSR | S_IXGRP | S_IXOTH)`.

Symlinks are preserved as-is (not followed, not permission-changed).

### 1.6 Staging Directory

Create a temporary staging directory and populate it with normalized content:

```bash
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT
chmod 0755 "$STAGING"
```

Copy/create each included entry:
- **Symlinks**: `os.symlink(os.readlink(src), dst)` — preserve target exactly
- **Binary files**: raw byte copy
- **Text files**: read → CRLF→LF → write
- **Directories**: `os.makedirs()` + `chmod(0o755)`

## Phase 2: Deterministic Tar Archive

Use GNU tar with options that eliminate all sources of non-determinism:

```bash
export LC_ALL=C   # force byte-order collation for deterministic sort

tar --sort=name \
    --mtime="@${EPOCH}" \
    --owner=0 --group=0 --numeric-owner \
    --format=gnu \
    -cf - \
    -C "$STAGING" .
```

| Option | Purpose |
|---|---|
| `LC_ALL=C` (env) | Force byte-order collation; prevents locale-dependent sort differences |
| `--sort=name` | Deterministic entry ordering by path name |
| `--mtime="@EPOCH"` | Uniform mtime for all entries (overrides filesystem mtime) |
| `--owner=0 --group=0` | Uniform ownership (root:root) |
| `--numeric-owner` | Use numeric IDs, not names (avoids name lookup variance) |
| `--format=gnu` | GNU tar format (consistent header layout) |
| `-C "$STAGING" .` | Archive from staging root |

**Epoch determination**: Use `SOURCE_DATE_EPOCH` environment variable if set, otherwise a fixed default (commonly `946684800` = 2000-01-01T00:00:00Z):

```bash
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"
```

## Phase 3: Deterministic Compression

Pipe tar output through the compressor with flags that ensure single-threaded, deterministic output:

```bash
... | zstd -19 --long --no-check --single-thread > output.tar.zst
```

| Flag | Purpose |
|---|---|
| `-19` | Maximum compression level |
| `--long` | Enable long-range mode for better compression |
| `--no-check` | Disable content checksum (eliminates checksum variance) |
| `--single-thread` | Single-threaded mode (eliminates thread-scheduling variance) |

## Key Invariants for Reproducibility

1. **Same input → same output**: For identical source tree and same `SOURCE_DATE_EPOCH`, the archive must be byte-identical across runs.
2. **No filesystem metadata leakage**: mtimes, ownership, and permissions are all normalized; only intentional values appear in the archive.
3. **Stable ordering**: `--sort=name` ensures entries appear in a deterministic order regardless of filesystem traversal order.
4. **Deterministic locale**: `export LC_ALL=C` must be set before any tar invocation. Without this, `--sort=name` uses locale-dependent collation (e.g., `en_US.UTF-8`), which can reorder paths containing `.`, `_`, mixed case, or special characters like `$` and `!`. This is a universal best practice in reproducible builds.
5. **Deterministic compression**: Single-threaded mode with no checksum ensures the compressed output depends only on the input bytes.
6. **Pax header hygiene** (for `--format=posix` only): When using pax/posix format, add `--pax-option=delete=atime,delete=ctime` to strip variable timestamps that tar would otherwise inject from the filesystem. GNU format (`--format=gnu`) does not use pax extended headers, so this flag is unnecessary and incompatible with it.

## Handling Edge Cases

- **Long filenames** (>100 chars): GNU tar format handles these natively; Python's `os` module has no path length limit on Linux.
- **Special characters** in filenames (`$`, `!`, spaces): Handled naturally by Python's `os` functions and GNU tar. Avoid shell expansion by using proper quoting.
- **Deep nesting**: `os.walk()` handles arbitrary depth; GNU tar stores full paths.
- **Symlinks**: Always preserved as symlinks (never dereferenced). Use `os.path.islink()` before `os.lstat()` to detect.
- **Empty directories**: Included if not excluded by ignore patterns (even if all their contents are excluded).
- **Files with future mtimes**: Overridden by `--mtime` flag, so original mtime is irrelevant.

## Variant Adaptation Guide

When adapting to variants within this family, these elements may change:

- **Ignore file name and format**: May be `.distignore`, `.tarignore`, or another name. Pattern syntax follows gitignore conventions.
- **Permission rules**: The specific permission values (0755/0644) and the shebang/exec detection logic may differ.
- **Text detection**: Null-byte heuristic is standard but variants might use `file` command or extension-based detection.
- **Line ending policy**: Some variants may require LF-only, others CRLF, others no normalization.
- **Timestamp source**: `SOURCE_DATE_EPOCH` is standard; default value may vary.
- **Compression tool**: May use `gzip`, `xz`, `zstd`, or `bzip2` with different flags.
- **Tar format**: May use `posix`/`pax` instead of `gnu`. When switching to `--format=posix`, you **must** add `--pax-option=delete=atime,delete=ctime` to strip variable filesystem timestamps (atime, ctime, dev, ino) from pax extended headers. Without this, pax archives are almost never reproducible because these fields vary between runs, machines, and containers. Note: `--pax-option` is incompatible with `--format=gnu` and will cause tar to fail if used together.
- **Archive root**: May include a top-level directory wrapper (e.g., `project-1.0/`).
