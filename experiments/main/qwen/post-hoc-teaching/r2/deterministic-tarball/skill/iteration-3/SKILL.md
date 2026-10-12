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

## Critical: Parameter Extraction from Task Instruction

**Before implementing, carefully read the task instruction to identify variant-specific parameters.** The spec allows variants to change many values. Do NOT assume v01 defaults apply to all variants.

### Parameter Extraction Checklist

Read the task instruction and extract these parameters:

| Parameter | v01 Default | What to Look For | Example Variants |
|-----------|-------------|------------------|------------------|
| **Sensitive file permission** | `0600` | "exclude files whose mode is exactly..." | `0400`, `0640`, `0440` |
| **Directory permission** | `0755` | "directories: ..." | `0700`, `0775` |
| **Executable file permission** | `0755` | "files with shebang or execute: ..." | `0700`, `0750` |
| **Regular file permission** | `0644` | "all other regular files: ..." | `0600`, `0664` |
| **Line ending normalization** | CRLF → LF | "Normalize line endings to..." | LF → CRLF, no normalization, CR → LF |
| **Default epoch** | `946684800` | "otherwise ..." (when SOURCE_DATE_EPOCH unset) | `0`, `1609459200` |
| **Owner/group** | `0:0` | "Set archive owner and group to..." | `1000:1000`, `65534:65534` |
| **Tar format** | `gnu` | "Use ... tar format" | `posix`, `pax` |
| **Compression command** | `zstd -19 --long --no-check --single-thread` | "Compress with..." | `gzip -9`, `xz -9e`, `zstd -T0 -19` |
| **Archive root layout** | Flat (no wrapper) | "wrap in...", "top-level directory..." | `project-1.0/`, `release/` |
| **Ignore file name** | `.distignore` | "Read exclusion rules from..." | `.tarignore`, `.releaseignore` |
| **Output path** | `/app/release.tar.zst` | "produces ..." | `/app/dist/release.tar.gz` |

**Implementation rule**: Define these as variables at the top of your script, populated from the task instruction. Never hardcode v01 values without checking the instruction first.

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

Exclude any regular file whose mode matches the **sensitive-file permission** specified in the task instruction (v01 uses `0600`). Check at build time — do not cache or assume pre-existing state:

```python
# Read from environment variable passed from bash
sensitive_perm = int(os.environ.get('SENSITIVE_PERM', '600'), 8)

fmode = stat.S_IMODE(os.lstat(path).st_mode)
if fmode == sensitive_perm:
    continue  # skip this file
```

**Important**: 
- This check must happen during the build, not before. Tests may change file permissions between setup and build execution.
- The permission value must be passed from bash to Python via environment variables (see Implementation Template). Do NOT hardcode it inside the Python code.

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

Apply the line ending normalization specified in the task instruction. Common patterns:

**CRLF → LF** (v01 default):
```python
data = data.replace(b'\r\n', b'\n')
```

**LF → CRLF**:
```python
data = data.replace(b'\r\n', b'\n')  # normalize first
data = data.replace(b'\n', b'\r\n')  # then convert to CRLF
```

**No normalization**: Skip this step entirely.

Binary files are always copied byte-for-byte without modification, regardless of line ending policy.

### 1.5 Permission Normalization

Apply the permission rules specified in the task instruction. v01 uses:

| Condition | Permission |
|---|---|
| Directory | `0755` |
| File has shebang (`#!`) OR any execute bit set | `0755` |
| All other regular files | `0644` |

**Read these values from environment variables** passed from bash (see Implementation Template):

```python
# Read from environment variables passed from bash
dir_perm = int(os.environ.get('DIR_PERM', '755'), 8)
exec_perm = int(os.environ.get('EXEC_PERM', '755'), 8)
file_perm = int(os.environ.get('FILE_PERM', '644'), 8)
```

Shebang detection: check if first 2 bytes are `#!`.
Execute detection: check `mode & (S_IXUSR | S_IXGRP | S_IXOTH)`.

Symlinks are preserved as-is (not followed, not permission-changed).

### 1.6 Staging Directory

Create a temporary staging directory and populate it with normalized content:

```bash
export STAGING=$(mktemp -d)  # ← export so Python can access via os.environ
trap 'rm -rf "$STAGING"' EXIT
chmod "$DIR_PERM" "$STAGING"
```

**Important**: The `STAGING` variable must be exported so the Python code can access it via `os.environ['STAGING']`.

Copy/create each included entry:
- **Symlinks**: `os.symlink(os.readlink(src), dst)` — preserve target exactly
- **Binary files**: raw byte copy
- **Text files**: read → apply line ending normalization → write
- **Directories**: `os.makedirs()` + `chmod(DIR_PERM)`

### 1.7 Archive Root Layout

Check the task instruction for archive root layout requirements:

**Flat layout (v01 default)**: Archive contents directly from staging root.

**Wrapped layout**: If the instruction says "wrap in `project-1.0/`" or similar:
```bash
# Create wrapper directory in staging
WRAPPER="$STAGING/project-1.0"
mkdir -p "$WRAPPER"
# Move all content into wrapper
for item in "$STAGING"/*; do
    [ "$item" = "$WRAPPER" ] && continue
    mv "$item" "$WRAPPER/"
done
```

Then archive from staging root as usual — the wrapper directory becomes the top-level entry.

## Phase 2: Deterministic Tar Archive

Use GNU tar with options that eliminate all sources of non-determinism. **Read the task instruction for format and ownership parameters.**

```bash
export LC_ALL=C   # force byte-order collation for deterministic sort

# v01 defaults — READ TASK INSTRUCTION for variant-specific values
TAR_FORMAT="gnu"     # or "posix"/"pax"
OWNER_ID=0           # numeric owner
GROUP_ID=0           # numeric group

tar --sort=name \
    --mtime="@${EPOCH}" \
    --owner=${OWNER_ID} --group=${GROUP_ID} --numeric-owner \
    --format=${TAR_FORMAT} \
    -cf - \
    -C "$STAGING" .
```

| Option | Purpose |
|---|---|
| `LC_ALL=C` (env) | Force byte-order collation; prevents locale-dependent sort differences |
| `--sort=name` | Deterministic entry ordering by path name |
| `--mtime="@EPOCH"` | Uniform mtime for all entries (overrides filesystem mtime) |
| `--owner=N --group=N` | Uniform ownership (read from task instruction) |
| `--numeric-owner` | Use numeric IDs, not names (avoids name lookup variance) |
| `--format=FORMAT` | Tar format (read from task instruction: gnu, posix, pax) |
| `-C "$STAGING" .` | Archive from staging root |

**Epoch determination**: Use `SOURCE_DATE_EPOCH` environment variable if set, otherwise a fixed default (commonly `946684800` = 2000-01-01T00:00:00Z):

```bash
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"
```

## Phase 3: Deterministic Compression

Pipe tar output through the compressor specified in the task instruction. The compressor must be run with flags that ensure deterministic output.

**v01 default**: zstd with maximum compression, long mode, no checksum, single thread:

```bash
... | zstd -19 --long --no-check --single-thread > output.tar.zst
```

| Flag | Purpose |
|---|---|
| `-19` | Maximum compression level |
| `--long` | Enable long-range mode for better compression |
| `--no-check` | Disable content checksum (eliminates checksum variance) |
| `--single-thread` | Single-threaded mode (eliminates thread-scheduling variance) |

**Variant compression commands** (read from task instruction):
- `gzip -9` — deterministic by default (single-threaded, no embedded timestamps in raw mode)
- `xz -9e` — deterministic by default (single-threaded at default)
- `zstd -T0 -19` — **NOT deterministic** (uses all cores); use `--single-thread` instead

**Critical rule**: Whatever compressor is specified, ensure it runs in single-threaded mode and does not embed variable metadata (timestamps, random seeds, etc.).

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

## Implementation Template

Use this template structure for your build script. Replace `# ← FROM TASK` values with parameters extracted from the task instruction.

**Critical: Passing parameters from bash to Python**

Bash variables are NOT automatically available inside a Python heredoc. You must either:
1. **Export as environment variables** (recommended): Use `export VAR=value` in bash, then read with `os.environ.get('VAR')` in Python
2. **Pass as command-line arguments**: Use `python3 - arg1 arg2` and read with `sys.argv[1]`, `sys.argv[2]`, etc.
3. **Use string interpolation**: Replace `'PYEOF'` with `PYEOF` (unquoted) and use `${VAR}` — but this is error-prone with Python code

The template below uses approach #1 (environment variables):

```bash
#!/bin/bash
set -euo pipefail
export LC_ALL=C

# === Parameters from task instruction ===
export SRC_DIR="/app/src"                    # ← FROM TASK (usually fixed)
export OUTPUT="/app/release.tar.zst"         # ← FROM TASK
export EPOCH="${SOURCE_DATE_EPOCH:-946684800}"  # ← default FROM TASK
export SENSITIVE_PERM="600"                  # ← FROM TASK (plain octal, NO "0o" prefix)
export DIR_PERM="755"                        # ← FROM TASK (plain octal, NO "0o" prefix)
export EXEC_PERM="755"                       # ← FROM TASK (plain octal, NO "0o" prefix)
export FILE_PERM="644"                       # ← FROM TASK (plain octal, NO "0o" prefix)
export TAR_FORMAT="gnu"                      # ← FROM TASK
export OWNER_ID="0"                          # ← FROM TASK
export GROUP_ID="0"                          # ← FROM TASK
export COMPRESS_CMD="zstd -19 --long --no-check --single-thread"  # ← FROM TASK

# Create staging directory
export STAGING=$(mktemp -d)  # ← export so Python can access it
trap 'rm -rf "$STAGING"' EXIT
chmod "$DIR_PERM" "$STAGING"

# Phase 1: Filter and normalize (Python)
python3 << 'PYEOF'
import os
import sys
import stat
import fnmatch

# Read parameters from environment
src_dir = os.environ['SRC_DIR']
staging_dir = os.environ['STAGING']
sensitive_perm = int(os.environ.get('SENSITIVE_PERM', '600'), 8)
dir_perm = int(os.environ.get('DIR_PERM', '755'), 8)
exec_perm = int(os.environ.get('EXEC_PERM', '755'), 8)
file_perm = int(os.environ.get('FILE_PERM', '644'), 8)

# ... rest of Python code uses these variables ...
PYEOF

# Phase 2 & 3: Deterministic tar + compression
tar --sort=name \
    --mtime="@${EPOCH}" \
    --owner=${OWNER_ID} --group=${GROUP_ID} --numeric-owner \
    --format=${TAR_FORMAT} \
    -cf - \
    -C "$STAGING" . \
  | ${COMPRESS_CMD} > "$OUTPUT"
```

**Alternative: Using command-line arguments**

If you prefer passing parameters as arguments:

```bash
python3 - "$SRC_DIR" "$STAGING" "$SENSITIVE_PERM" "$DIR_PERM" "$EXEC_PERM" "$FILE_PERM" << 'PYEOF'
import os
import sys

src_dir = sys.argv[1]
staging_dir = sys.argv[2]
sensitive_perm = int(sys.argv[3], 8)
dir_perm = int(sys.argv[4], 8)
exec_perm = int(sys.argv[5], 8)
file_perm = int(sys.argv[6], 8)

# ... rest of Python code ...
PYEOF
```

**Why this matters for variants:**
If a variant changes the sensitive permission to 0400, your script must read that value from the task instruction and use it. Hardcoding 0600 will cause test failures.

## Common Pitfalls

1. **Hardcoding v01 values**: Always check the task instruction for variant-specific parameters.
2. **Caching ignore patterns**: Read `.distignore` at build time, not at script-creation time.
3. **Missing `LC_ALL=C`**: Without this, sort order varies by locale.
4. **Pax format without `--pax-option`**: Pax archives include variable metadata by default.
5. **Following symlinks**: Always use `os.path.islink()` before `os.lstat()`; never dereference.
6. **Binary detection on empty files**: Empty files have no null bytes → treated as text (correct).
7. **0600 check timing**: Check file mode at build time, not at script-creation time.
8. **Ignoring archive root layout**: Some variants wrap content in a top-level directory.
9. **Using `0o` prefix in bash chmod**: `chmod 0o755` fails — bash `chmod` expects plain octal `755`, not Python-style `0o755`. Export permissions as plain octal strings (e.g., `"755"` not `"0o755"`); Python's `int("755", 8)` parses them correctly.
