---
name: deterministic-tarball
description: >
  Build a bit-for-bit reproducible compressed tar archive from a source tree,
  honoring .distignore exclusion rules, excluding sensitive (0600) files,
  normalizing permissions/line-endings/mtime/ownership, preserving symlinks,
  and compressing with zstd. Produces identical output for identical input
  regardless of filesystem metadata or build environment.
---

# Deterministic Tarball Packaging

## Overview

This skill creates a deterministic release archive from an existing project source tree.
The archive must be bit-for-bit reproducible: running the build twice with the same
`SOURCE_DATE_EPOCH` must produce byte-identical output.

## Core Architecture

The build process has three phases:

1. **Staging**: Walk the source tree, apply exclusion rules, normalize content and metadata into a temporary staging directory.
2. **Archiving**: Create a GNU tar archive from the staging directory with deterministic ordering and fixed metadata.
3. **Compression**: Pipe the tar stream through zstd with deterministic compression settings.

## Phase 1: Staging Directory Construction

### 1.1 Parse .distignore

Read the `.distignore` file from the source root. Each non-empty, non-comment line is an exclusion pattern:

| Pattern form | Meaning | Example |
|---|---|---|
| `dirname/` | Exclude directory (and contents) at source root | `.hg/`, `scratch/` |
| `**/dirname/` | Exclude directory at any depth | `**/__pycache__/` |
| `*.ext` | Exclude files matching glob at any depth | `*.tmp`, `*.pyc`, `*.o` |

**Implementation**: Use `fnmatch` for glob matching. Parse patterns into three categories:
- `dir_patterns`: root-relative directory names (trailing `/` stripped)
- `deep_dir_patterns`: recursive directory names (`**/` prefix stripped)
- `file_patterns`: filename glob patterns

For each candidate path, check:
1. Does any path component match a `deep_dir_pattern`?
2. Does the first path component or the full path match a `dir_pattern`?
3. Does the basename match any `file_pattern`?

### 1.2 Exclude 0600 Files

Any regular file whose permission mode is exactly `0600` must be excluded, regardless of `.distignore`. Check with `os.lstat()` and mask with `0o7777`.

### 1.3 Binary vs Text Detection

Detect binary files by checking for null bytes (`\x00`) in the first 8192 bytes:
- **Binary**: Copy unchanged (preserves exact bytes including any line endings)
- **Text**: Convert all CRLF (`\r\n`) to LF (`\n`)

### 1.4 Permission Normalization

Apply these rules to all entries in the staging directory:
- **Directories**: `0755`
- **Files with shebang** (`#!` as first two bytes) **or execute bit set**: `0755`
- **All other regular files**: `0644`
- **Symlinks**: Preserve as-is (do not follow or modify)

### 1.5 Timestamp Normalization

**Two layers of mtime control, with clear authority:**

- **`tar --mtime="@EPOCH"`** (Phase 2) is the **authoritative mechanism**. It overrides every mtime in the archive headers regardless of what the filesystem says. This is what actually makes the archive deterministic.
- **`os.utime()` on staging files** (Phase 1) is **defense-in-depth**. It sets filesystem mtimes that tar would use *only if `--mtime` were absent*.

When both are present and agree, the output is correct. When they disagree, `--mtime` wins. For variants that need per-file timestamps (e.g., from git history), remove `--mtime` and rely solely on staging filesystem mtimes — in that case the `os.utime()` pass becomes the only mechanism and must be correct.

Default epoch: `SOURCE_DATE_EPOCH` environment variable if set, otherwise `946684800` (2000-01-01T00:00:00Z).

### 1.6 Ownership Normalization

All archive entries use numeric owner `0` and group `0`.

### 1.7 Empty-Directory Cleanup

After the main walk, perform a bottom-up pass to remove directories whose contents were entirely excluded:

```python
for dirpath, dirnames, filenames in os.walk(staging, topdown=False):
    if dirpath != staging and not os.listdir(dirpath):
        os.rmdir(dirpath)
```

This prevents empty leaf directories (e.g., `keys/` whose only file was 0600-excluded) from appearing in the archive.

## Phase 2: Tar Archive Creation

Use GNU tar with these flags for determinism:

```bash
tar --create \
    --format=gnu \
    --sort=name \
    --mtime="@${MTIME}" \
    --owner=0 --group=0 \
    --numeric-owner \
    --file=- \
    .
```

Key flags:
- `--format=gnu`: Use GNU tar format (handles long filenames)
- `--sort=name`: Deterministic entry ordering
- `--mtime="@EPOCH"`: **Authoritative** fixed modification time for all entries
- `--owner=0 --group=0 --numeric-owner`: Fixed ownership
- `--file=-`: Output to stdout for piping

## Phase 3: Compression

Pipe tar output to zstd with deterministic settings:

```bash
zstd -19 --long --no-check --single-thread
```

Key flags:
- `-19`: Maximum compression level
- `--long`: Enable long-distance matching
- `--no-check`: Omit content checksum (avoids non-deterministic metadata)
- `--single-thread`: Ensure single-threaded operation for reproducibility

## Implementation Pattern

The recommended implementation uses a shell script (`build.sh`) that delegates complex logic to an inline Python script:

```bash
#!/bin/bash
set -euo pipefail

SRC_DIR="/app/src"
OUTPUT="/app/release.tar.zst"
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
MTIME="${SOURCE_DATE_EPOCH:-946684800}"

# Phase 1: Python handles exclusion, normalization, staging
python3 - "$SRC_DIR" "$STAGING" "$MTIME" <<'PYEOF'
import os, sys, stat, shutil, fnmatch

src_dir, staging, mtime = sys.argv[1], sys.argv[2], int(sys.argv[3])

# ── Parse .distignore ──────────────────────────────────────────────
dir_patterns, file_patterns, deep_dir_patterns = [], [], []
distignore_path = os.path.join(src_dir, ".distignore")
if os.path.isfile(distignore_path):
    with open(distignore_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("**/"):
                inner = line[3:]
                if inner.endswith("/"):
                    deep_dir_patterns.append(inner.rstrip("/"))
                else:
                    file_patterns.append(inner)
            elif line.endswith("/"):
                dir_patterns.append(line.rstrip("/"))
            else:
                file_patterns.append(line)

# ── Exclusion matching ─────────────────────────────────────────────
def is_excluded(relpath):
    parts = relpath.split(os.sep)
    basename = parts[-1]
    # Deep patterns: match any path component
    for dp in deep_dir_patterns:
        if any(fnmatch.fnmatch(part, dp) for part in parts):
            return True
    # Dir patterns: root-anchored with startswith
    for dp in dir_patterns:
        if relpath == dp or relpath.startswith(dp + os.sep):
            return True
    # File patterns: match basename
    for fp in file_patterns:
        if fnmatch.fnmatch(basename, fp):
            return True
    return False

# ── Binary detection: null byte in first 8 KiB ────────────────────
def is_binary(filepath):
    with open(filepath, "rb") as f:
        return b"\x00" in f.read(8192)

# ── Shebang detection for permission normalization ─────────────────
def has_shebang(filepath):
    with open(filepath, "rb") as f:
        return f.read(2) == b"#!"

# ── Walk loop: key decisions ───────────────────────────────────────
# - followlinks=False (default) to not follow symlinks
# - dirnames[:] = filtered to prune excluded dirs in-place
# - os.lstat (not os.stat) for symlink detection
# - 0o7777 mask for mode checks

for dirpath, dirnames, filenames in os.walk(src_dir):
    rel_dir = os.path.relpath(dirpath, src_dir)
    if rel_dir == ".":
        rel_dir = ""

    # Prune excluded directories in-place
    dirnames[:] = [
        d for d in sorted(dirnames)
        if not is_excluded(os.path.join(rel_dir, d) if rel_dir else d)
    ]

    # Create directory in staging
    if rel_dir:
        staging_dir = os.path.join(staging, rel_dir)
        os.makedirs(staging_dir, exist_ok=True)
        os.chmod(staging_dir, 0o755)

    for fname in filenames:
        rel_path = os.path.join(rel_dir, fname) if rel_dir else fname
        src_path = os.path.join(dirpath, fname)

        if is_excluded(rel_path):
            continue

        st = os.lstat(src_path)  # lstat, not stat!

        # Symlinks: preserve as-is
        if stat.S_ISLNK(st.st_mode):
            dst_path = os.path.join(staging, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            if os.path.lexists(dst_path):
                os.remove(dst_path)
            os.symlink(os.readlink(src_path), dst_path)
            continue

        if stat.S_ISREG(st.st_mode):
            # Exclude 0600 files
            if (st.st_mode & 0o7777) == 0o600:
                continue

            dst_path = os.path.join(staging, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)

            if is_binary(src_path):
                shutil.copy2(src_path, dst_path)
            else:
                with open(src_path, "rb") as f:
                    data = f.read()
                data = data.replace(b"\r\n", b"\n")  # CRLF → LF
                with open(dst_path, "wb") as f:
                    f.write(data)

            # Permission normalization
            if has_shebang(src_path) or (st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
                os.chmod(dst_path, 0o755)
            else:
                os.chmod(dst_path, 0o644)

            os.utime(dst_path, (mtime, mtime))

# ── Empty-directory cleanup (bottom-up) ────────────────────────────
for dirpath, dirnames, filenames in os.walk(staging, topdown=False):
    if dirpath != staging and not os.listdir(dirpath):
        os.rmdir(dirpath)
    elif os.path.isdir(dirpath):
        os.utime(dirpath, (mtime, mtime))
        os.chmod(dirpath, 0o755)
PYEOF

# Phase 2+3: Tar and compress
cd "$STAGING"
tar --create --format=gnu --sort=name \
    --mtime="@${MTIME}" --owner=0 --group=0 --numeric-owner \
    --file=- . \
  | zstd -19 --long --no-check --single-thread \
  > "$OUTPUT"
```

## Critical Edge Cases

1. **Filenames with spaces and special characters**: Use Python's `os.walk()` which handles these natively. Avoid shell globbing.
2. **Very long filenames** (>100 chars): GNU tar format handles these; no special action needed.
3. **Deep directory nesting**: `os.walk()` handles arbitrary depth.
4. **Symlinks**: Use `os.lstat()` (not `os.stat()`) to detect symlinks without following. Recreate with `os.symlink()`.
5. **Empty files**: Treat as text (no null bytes → text path → CRLF→LF conversion is a no-op on empty content).
6. **Files with mixed content** (text + null bytes): Treat as binary (null byte detection triggers binary path).
7. **Empty directories after exclusion**: Remove from staging via bottom-up `os.rmdir` pass to avoid unnecessary entries in the archive.

## Reproducibility Checklist

- [ ] All mtimes fixed to single epoch value (via `--mtime` authoritatively)
- [ ] All ownership fixed to 0:0
- [ ] All permissions normalized (no source filesystem leakage)
- [ ] Tar entries sorted by name
- [ ] zstd runs single-threaded with no checksum
- [ ] No filesystem-dependent behavior (locale, timezone, umask)
- [ ] Symlinks stored as symlinks, not dereferenced
- [ ] Binary files copied byte-for-byte
- [ ] Text files have normalized line endings
- [ ] Empty directories from excluded content are cleaned up

## Adaptation Guide

When facing a variant of this task family:

1. **Read the task instructions carefully** for the exact:
   - Source tree location
   - Output archive path
   - .distignore location and format
   - Permission normalization rules
   - Compression command and flags
   - Default epoch value

2. **Check for variations** in:
   - Which file modes trigger exclusion (may not always be 0600)
   - How text vs binary is determined (null byte check is common but not universal)
   - Line ending requirements (CRLF→LF is common; some variants may need LF→CRLF)
   - Tar format (GNU, POSIX/PAX, etc.)
   - Compression tool and flags
   - Timestamp source (may need per-file timestamps from git history instead of a single epoch)

3. **mtime layering**: If a variant changes the timestamp source, understand that `--mtime` overrides everything in tar headers. To use per-file timestamps, remove `--mtime` and ensure staging filesystem mtimes are set correctly via `os.utime()`.

4. **The staging directory approach** is robust across variants because it decouples normalization from archiving.
