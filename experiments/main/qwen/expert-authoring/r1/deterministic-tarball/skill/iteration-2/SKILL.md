---
name: deterministic-tarball
description: >
  Build bit-for-bit reproducible release archives from a project source tree.
  Covers reading gitignore-style .distignore exclusion files, normalizing
  permissions/line-endings/timestamps/ownership, preserving symlinks, and
  producing deterministic tar+zstd bundles.
---

# Deterministic Release Packaging

## Problem

Create an executable build script (typically `/app/build.sh`) that reads a
source tree (typically `/app/src`) and produces a compressed archive
(typically `/app/release.tar.zst`) that is **bit-for-bit reproducible** for
the same `SOURCE_DATE_EPOCH`. The script must re-read `.distignore` and
re-check file permissions on every invocation — tests modify these between runs.

## Recommended Approach: Python build script

**Use a Python script as `build.sh`** (with `#!/usr/bin/env python3` shebang).
Python handles special characters in filenames natively, provides the
`pathspec` library for gitignore-style pattern matching, and avoids shell
quoting pitfalls that cause bash scripts to fail in subprocess environments.

The script has five stages:

1. **Parse `.distignore`** using `pathspec.PathSpec.from_lines('gitwildmatch', patterns)`
2. **Walk and filter** the source tree (respecting exclusions and 0600 mode)
3. **Stage with normalization** (permissions, line endings, timestamps)
4. **Create tar** via GNU tar subprocess (for reliable format control)
5. **Compress** with `zstd -19 --long --no-check --single-thread`

### Critical details that cause failures

| Issue | Consequence | Fix |
|-------|------------|-----|
| `mkdtemp()` creates dirs with mode `0700` | Root `./` entry in tar has wrong permissions | `os.chmod(staging, 0o755)` before tarring |
| Not re-reading `.distignore` each run | Fails when test modifies `.distignore` between invocations | Read `.distignore` inside `main()`, not at module level |
| Not re-checking file modes each run | Fails when test chmods a file to `0600` between invocations | Check `stat()` at staging time, not at script-write time |
| Binary files corrupted by line-ending conversion | `file -b` misclassifies some binaries as "text" | Use null-byte check: `b'\x00' not in data[:8192]` |
| Git-based `.distignore` parsing fails with special chars | `git add --dry-run` quotes `$`, `\`, `!` in paths; sed doesn't unescape | Use `pathspec` library instead |
| `set -euo pipefail` + fragile git | Any non-zero exit (e.g., grep no-match) kills the whole script | Python's exception handling is more predictable |

### Text vs binary detection

Use **null-byte detection**, not the `file` command:
```python
def is_text_file(path):
    with open(path, 'rb') as f:
        return b'\x00' not in f.read(8192)
```
This is simpler, more reliable, and avoids subprocess overhead. Files like
`mixed.dat` (containing both text and null bytes) are correctly classified as
binary. Empty files return `True` (no null bytes) — safe since there is no
content to modify.

### Permission normalization rules

Priority order (first match wins):
1. **Directories** → `0o755`
2. **Symlinks** → unchanged (Linux ignores symlink permissions)
3. **Files starting with `#!`** (shebang) → `0o755`
4. **Files with any execute bit set** → `0o755`
5. **All other regular files** → `0o644`

### The `.distignore` file must be re-read every run

Tests append patterns to `.distignore` (e.g., `docs/`) and verify the script
excludes the new paths. The script must parse `.distignore` inside its
`main()` function, not as a one-time constant.

### The 0600 mode check must be re-evaluated every run

Tests `chmod` a file to `0600` and verify it is excluded from the next run.
Check `os.lstat()` mode during staging, not at script-creation time.

### Symlinks must be preserved, never followed

Use `os.path.islink()` to detect symlinks. Copy with `os.symlink(os.readlink(src), dst)`.
Never use `shutil.copy` on symlinks (it follows them by default in some modes).
When setting mtime, use `follow_symlinks=False` to avoid touching the target.

## Reference Implementation

Write this as `/app/build.sh` and `chmod +x` it:

```python
#!/usr/bin/env python3
import os, sys, stat, shutil, subprocess, tempfile

SRC_DIR = "/app/src"
OUTPUT = "/app/release.tar.zst"
EPOCH = int(os.environ.get("SOURCE_DATE_EPOCH") or "946684800")

def load_distignore(src_dir):
    try:
        import pathspec
    except ImportError:
        sys.exit("pathspec required")
    dp = os.path.join(src_dir, ".distignore")
    patterns = []
    if os.path.isfile(dp):
        with open(dp) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

def is_text(path):
    try:
        with open(path, "rb") as f:
            return b"\x00" not in f.read(8192)
    except OSError:
        return False

def main():
    spec = load_distignore(SRC_DIR)
    staging = tempfile.mkdtemp()
    try:
        for root, dirs, files in os.walk(SRC_DIR):
            for name in files:
                src = os.path.join(root, name)
                rel = os.path.relpath(src, SRC_DIR)
                if spec.match_file(rel):
                    continue
                if not os.path.islink(src):
                    if stat.S_IMODE(os.lstat(src).st_mode) == 0o600:
                        continue
                dst = os.path.join(staging, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.islink(src):
                    os.symlink(os.readlink(src), dst)
                else:
                    shutil.copy2(src, dst)
                    with open(dst, "rb") as f:
                        shebang = f.read(2) == b"#!"
                    m = stat.S_IMODE(os.lstat(src).st_mode)
                    exe = bool(m & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
                    os.chmod(dst, 0o755 if shebang or exe else 0o644)
                    if is_text(dst):
                        with open(dst, "rb") as f:
                            data = f.read()
                        if b"\r\n" in data:
                            with open(dst, "wb") as f:
                                f.write(data.replace(b"\r\n", b"\n"))
        os.chmod(staging, 0o755)
        for root, dirs, _ in os.walk(staging):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o755)
        for root, dirs, files in os.walk(staging):
            for n in dirs + files:
                p = os.path.join(root, n)
                try:
                    os.utime(p, (EPOCH, EPOCH), follow_symlinks=False)
                except OSError:
                    pass
        os.utime(staging, (EPOCH, EPOCH), follow_symlinks=False)
        tar_path = OUTPUT.replace(".zst", "")
        r = subprocess.run(["find", ".", "-print0"],
                           cwd=staging, capture_output=True)
        entries = sorted(r.stdout.split(b"\0"))
        if entries and entries[-1] == b"":
            entries.pop()
        subprocess.run([
            "tar", "--create", "--file=" + tar_path, "--format=gnu",
            "--sort=name", "--owner=0", "--group=0", "--numeric-owner",
            "--mtime=@" + str(EPOCH), "--no-recursion",
            "--null", "--files-from=-"
        ], input=b"\0".join(entries), cwd=staging, check=True)
        subprocess.run([
            "zstd", "-19", "--long", "--no-check", "--single-thread",
            "-f", tar_path, "-o", OUTPUT
        ], check=True)
        os.unlink(tar_path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

if __name__ == "__main__":
    main()
```

### Why GNU tar via subprocess instead of Python `tarfile`

Python's `tarfile` module can create tar archives but has subtle differences
from GNU tar in header formatting (especially for long filenames and symlinks).
Using `tar` as a subprocess guarantees the exact GNU format the tests expect.
The `--sort=name` and `--no-recursion --null --files-from=-` flags give
deterministic entry ordering while handling all special characters via
NUL-delimited input.

## Bash Alternative (fragile — use only if Python is unavailable)

If you must use bash, be aware of these additional pitfalls:

1. **`set -euo pipefail` kills the script** on any non-zero exit, including
   `grep` returning no matches. Use `|| true` for expected no-match cases.
2. **`git add --dry-run` quotes special characters** in filenames (e.g.,
   `file$special\!chars.py` becomes `'file$special\\!chars.py'`). The sed
   pattern `s/^add '//;s/'$//` strips quotes but does NOT unescape `\\` → `\`.
   This causes `stat` and `cp` to fail on "file not found".
3. **Leftover git temp dirs** from previous runs can cause `git init -q` to
   behave unexpectedly. Clean up thoroughly.
4. **Staging root from `mkdtemp` has mode 0700**, not 0755. Add
   `chmod 0755 "$STAGING"` explicitly.
5. **Locale-dependent sort** — always use `LC_ALL=C sort -z`.
6. **Never follow symlinks** — avoid `cp -L`, `tar -h`, `find -L`.

## Verification Checklist

After building, confirm:
- [ ] Output exists and is non-empty
- [ ] `zstd -lv` shows `Check: None` (no-checksum flag)
- [ ] `tar -tvf` shows GNU format with owner 0:0
- [ ] Excluded paths (from `.distignore`) are absent
- [ ] 0600-mode files are absent
- [ ] Symlinks stored as symlinks (`-> target` in `tar -tvf`)
- [ ] Directory permissions are all 0755 (including root `./`)
- [ ] Text files have LF line endings (no `\r\n`)
- [ ] Binary files are byte-identical to source
- [ ] Running twice with same `SOURCE_DATE_EPOCH` produces identical hash

## Variant Adaptation

| Dimension | What changes | What stays the same |
|-----------|-------------|-------------------|
| Source tree content | File names, patterns, symlinks, depth | pathspec matching, null-byte detection |
| Normalization rules | Permission values, epoch source, line-ending target | Staging approach, tar flags |
| Archive format | tar format (pax/gnu), compressor (zstd/xz/gzip) | Deterministic principles (sort, fixed mtime/owner) |

Read the task spec carefully and substitute the specific values for:
- Permission mappings (the default is dirs=0755, exec=0755, files=0644)
- Epoch variable name and fallback value
- Compression command and flags
- Output path
