---
name: deterministic-tarball
description: >
  Build a bit-for-bit reproducible compressed tar archive from a source tree,
  honoring .distignore exclusion rules, excluding sensitive files by mode,
  normalizing permissions/line-endings/mtime/ownership, preserving symlinks,
  and compressing with deterministic settings. Produces identical output for
  identical input regardless of filesystem metadata or build environment.
---

# Deterministic Tarball Packaging

## Overview

This skill creates a deterministic release archive from an existing project source tree.
The archive must be bit-for-bit reproducible: running the build twice with the same
`SOURCE_DATE_EPOCH` must produce byte-identical output.

## Core Architecture

The build process has three phases:

1. **Staging**: Walk the source tree, apply exclusion rules, normalize content and metadata into a temporary staging directory.
2. **Archiving**: Create a tar archive from the staging directory with deterministic ordering and fixed metadata.
3. **Compression**: Pipe the tar stream through a compressor with deterministic settings.

## Phase 1: Staging Directory Construction

### 1.1 Parse .distignore

Read the `.distignore` file from the source root. Each non-empty, non-comment line is an exclusion pattern:

| Pattern form | Meaning | Example |
|---|---|---|
| `dirname/` | Exclude directory (and contents) at source root | `.hg/`, `scratch/` |
| `path/to/dir/` | Exclude nested directory at source root | `vendor/js/` |
| `**/dirname/` | Exclude directory at any depth | `**/__pycache__/` |
| `*.ext` | Exclude files matching glob at any depth | `*.tmp`, `*.pyc`, `*.o` |

**Implementation**: Use `fnmatch` for glob matching. Parse patterns into three categories:
- `dir_patterns`: root-relative directory paths (trailing `/` stripped)
- `deep_dir_patterns`: recursive directory names (`**/` prefix stripped)
- `file_patterns`: filename glob patterns

For each candidate path, check:
1. Does any path component match a `deep_dir_pattern`?
2. Does the path equal or start with a `dir_pattern`?
3. Does the basename match any `file_pattern`?

### 1.2 Exclude Sensitive Files

Any regular file whose permission mode matches the sensitive threshold must be excluded, regardless of `.distignore`. The default threshold is `0600` but **check the task instructions** — variants may specify different modes. Check with `os.lstat()` and mask with `0o7777`.

### 1.3 Binary vs Text Detection

Detect binary files by checking for null bytes (`\x00`) in the first 8192 bytes:
- **Binary**: Copy unchanged (preserves exact bytes including any line endings)
- **Text**: Convert line endings as specified (default: CRLF `\r\n` → LF `\n`)

**Note**: The detection heuristic and conversion rules may vary by task. The null-byte check is common but not universal.

### 1.4 Permission Normalization

Apply these rules to all entries in the staging directory (default values — **check task instructions**):
- **Directories**: `0755`
- **Files with shebang** (`#!` as first two bytes) **or execute bit set**: `0755`
- **All other regular files**: `0644`
- **Symlinks**: Preserve as-is (do not follow or modify)

### 1.5 Timestamp Normalization

**Two layers of mtime control, with clear authority:**

- **`tar --mtime="@EPOCH"`** (Phase 2) is the **authoritative mechanism**. It overrides every mtime in the archive headers regardless of what the filesystem says. This is what actually makes the archive deterministic.
- **`os.utime()` on staging files** (Phase 1) is **defense-in-depth**. It sets filesystem mtimes that tar would use *only if `--mtime` were absent*.

When both are present and agree, the output is correct. When they disagree, `--mtime` wins. For variants that need per-file timestamps (e.g., from git history), remove `--mtime` and rely solely on staging filesystem mtimes — in that case the `os.utime()` pass becomes the only mechanism and must be correct.

Default epoch: `SOURCE_DATE_EPOCH` environment variable if set, otherwise the value specified in the task instructions (v01 uses `946684800` = 2000-01-01T00:00:00Z).

### 1.6 Ownership Normalization

All archive entries use the numeric owner and group specified in the task instructions (default: `0:0`).

### 1.7 Empty-Directory Cleanup

After the main walk, perform a bottom-up pass to remove directories whose contents were entirely excluded:

```python
for dirpath, dirnames, filenames in os.walk(staging, topdown=False):
    if dirpath != staging and not os.listdir(dirpath):
        os.rmdir(dirpath)
```

This prevents empty leaf directories (e.g., `keys/` whose only file was excluded by mode) from appearing in the archive.

### 1.8 Archive Root Layout

The archive may require all entries to be under a specific prefix directory (e.g., `./release-1.0/...` instead of `./...`). **Check the task instructions** for the expected root layout.

**Default (no prefix)**: Archive entries directly from the staging root. This is the v01 behavior where paths appear as `./app/src/main.c`.

**With prefix**: If the task requires a prefix directory:
1. After populating the staging directory with normalized content, create a new wrapper directory
2. Move all staging content into a subdirectory named with the prefix
3. Archive from the wrapper directory root

```python
# Example: adding archive root prefix
archive_prefix = "release-1.0"  # From task instructions, or None/"" for no prefix

if archive_prefix:
    wrapper = os.path.join(staging, "__wrapper__")
    os.makedirs(wrapper, exist_ok=True)
    # Move all content into prefix subdirectory
    for entry in os.listdir(staging):
        if entry == "__wrapper__":
            continue
        src = os.path.join(staging, entry)
        dst = os.path.join(wrapper, archive_prefix)
        os.makedirs(dst, exist_ok=True)
        shutil.move(src, os.path.join(dst, entry))
    # Move wrapper contents back to staging root
    for entry in os.listdir(wrapper):
        shutil.move(os.path.join(wrapper, entry), os.path.join(staging, entry))
    os.rmdir(wrapper)
    # Set metadata on prefix directory
    prefix_path = os.path.join(staging, archive_prefix)
    os.utime(prefix_path, (mtime, mtime))
    os.chmod(prefix_path, 0o755)
```

**Alternative approach using tar --transform**:
```bash
tar --transform="s,^,${PREFIX}/," --create ...
```

The staging subdirectory approach is preferred because it gives full control over the prefix directory's metadata (permissions, mtime, ownership) and is consistent with the overall architecture.

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

**Note**: The tar format and ownership values may vary by task. Check the task instructions for the exact flags to use.

## Phase 3: Compression

Pipe tar output to the compressor with deterministic settings (v01 uses zstd):

```bash
zstd -19 --long --no-check --single-thread
```

Key flags:
- `-19`: Maximum compression level
- `--long`: Enable long-distance matching
- `--no-check`: Omit content checksum (avoids non-deterministic metadata)
- `--single-thread`: Ensure single-threaded operation for reproducibility

**Note**: The compression tool and flags may vary by task. The key principle is that the compressor must produce deterministic output for the same input.

## Implementation Pattern

The recommended implementation uses a shell script (`build.sh`) that delegates complex logic to an inline Python script:

```bash
#!/bin/bash
set -euo pipefail

# ── Parameters (extract from task instructions) ──────────────────────
SRC_DIR="/app/src"                    # Source tree root
OUTPUT="/app/release.tar.zst"         # Output archive path
SENSITIVE_MODE=600                    # File mode to exclude (raw octal digits)
ARCHIVE_PREFIX=""                     # Prefix for archive root ("" = no prefix)
MTIME="${SOURCE_DATE_EPOCH:-946684800}"  # Default epoch

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

# Phase 1: Python handles exclusion, normalization, staging
python3 - "$SRC_DIR" "$STAGING" "$MTIME" "$SENSITIVE_MODE" <<'PYEOF'
import os, sys, stat, shutil, fnmatch

src_dir, staging, mtime = sys.argv[1], sys.argv[2], int(sys.argv[3])
sensitive_mode = int(sys.argv[4], 8)

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
            # Exclude sensitive files by mode
            if (st.st_mode & 0o7777) == sensitive_mode:
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

# ── Archive root layout: add prefix if required ────────────────────
if [ -n "$ARCHIVE_PREFIX" ]; then
    python3 - "$STAGING" "$ARCHIVE_PREFIX" "$MTIME" <<'PREFXEOF'
import os, sys, shutil
staging, prefix, mtime = sys.argv[1], sys.argv[2], int(sys.argv[3])
wrapper = os.path.join(staging, "__wrapper__")
os.makedirs(wrapper, exist_ok=True)
prefix_dir = os.path.join(wrapper, prefix)
os.makedirs(prefix_dir, exist_ok=True)
for entry in os.listdir(staging):
    if entry == "__wrapper__":
        continue
    shutil.move(os.path.join(staging, entry), os.path.join(prefix_dir, entry))
for entry in os.listdir(wrapper):
    shutil.move(os.path.join(wrapper, entry), os.path.join(staging, entry))
os.rmdir(wrapper)
os.utime(os.path.join(staging, prefix), (mtime, mtime))
os.chmod(os.path.join(staging, prefix), 0o755)
PREFXEOF
fi

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
5. **Empty files**: Treat as text (no null bytes → text path → line-ending conversion is a no-op on empty content).
6. **Files with mixed content** (text + null bytes): Treat as binary (null byte detection triggers binary path).
7. **Empty directories after exclusion**: Remove from staging via bottom-up `os.rmdir` pass to avoid unnecessary entries in the archive.
8. **Archive root prefix**: If required, wrap all content in a prefix directory after normalization but before archiving. Ensure the prefix directory itself has correct metadata.

## Reproducibility Checklist

- [ ] All mtimes fixed to single epoch value (via `--mtime` authoritatively)
- [ ] All ownership fixed to specified numeric values
- [ ] All permissions normalized (no source filesystem leakage)
- [ ] Tar entries sorted by name
- [ ] Compressor runs in deterministic mode (single-threaded, no checksums)
- [ ] No filesystem-dependent behavior (locale, timezone, umask)
- [ ] Symlinks stored as symlinks, not dereferenced
- [ ] Binary files copied byte-for-byte
- [ ] Text files have normalized line endings
- [ ] Empty directories from excluded content are cleaned up
- [ ] Archive root layout matches task requirements (prefix if specified)

## Adaptation Guide

When facing a variant of this task family:

1. **Read the task instructions carefully** for the exact:
   - Source tree location
   - Output archive path
   - .distignore location and format
   - Permission normalization rules (directory, executable, regular file modes)
   - Sensitive file mode threshold (may not be 0600)
   - Compression command and flags
   - Default epoch value
   - Owner/group numeric IDs
   - **Archive root layout** (prefix directory if any)

2. **Check for variations** in:
   - Which file modes trigger exclusion (may not always be 0600)
   - How text vs binary is determined (null byte check is common but not universal)
   - Line ending requirements (CRLF→LF is common; some variants may need LF→CRLF or no conversion)
   - Tar format (GNU, POSIX/PAX, etc.)
   - Compression tool and flags
   - Timestamp source (may need per-file timestamps from git history instead of a single epoch)
   - Owner/group policy (may not be 0:0)
   - Archive root layout (files may need to be under a prefix directory)

3. **mtime layering**: If a variant changes the timestamp source, understand that `--mtime` overrides everything in tar headers. To use per-file timestamps, remove `--mtime` and ensure staging filesystem mtimes are set correctly via `os.utime()`.

4. **The staging directory approach** is robust across variants because it decouples normalization from archiving. This makes it easy to add prefix directories, change permission rules, or modify any other aspect of the content before creating the final archive.

5. **Dynamic behavior**: The build script must read `.distignore` and check file modes at runtime (not cache them). Tests may modify `.distignore` or file permissions between runs and expect the script to pick up the changes.
