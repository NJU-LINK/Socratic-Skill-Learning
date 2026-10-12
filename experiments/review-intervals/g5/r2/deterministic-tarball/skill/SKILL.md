---
name: deterministic-tarball
description: >
  Build a bit-for-bit reproducible tarball (.tar.zst or other compressed format)
  from a project source tree, honoring ignore-file exclusions, excluding
  sensitive (0600) files, normalizing permissions/line-endings/timestamps, and
  using deterministic archive and compression settings.
---

# Deterministic Tarball Packaging

## When This Skill Applies

Use this skill when a task asks you to create a **reproducible / deterministic release archive** from a source tree. Typical signals in the task description:

- "deterministic tarball", "reproducible archive", "release packaging"
- Requirements for bit-for-bit reproducibility given the same `SOURCE_DATE_EPOCH`
- An ignore file (`.distignore`, `.gitignore`, etc.) defining what to exclude
- Metadata normalization rules (permissions, timestamps, line endings, owner/group)
- Specific compression algorithm and flags

## Core Algorithm: Staging-Copy → Normalize → Archive

The pipeline has three phases. Each phase is independent and can be tested separately.

### Phase 1: Staging Copy

Copy the entire source tree into a temporary staging directory. This avoids mutating the original source and gives you a sandbox for in-place normalization.

```bash
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT
cp -a "$SRC/." "$STAGING/"
```

Key: `cp -a` preserves symlinks, permissions, and timestamps from the original.

### Phase 2: Exclusions

Two categories of exclusions must be applied:

#### 2a. Ignore-file patterns (.distignore / .gitignore-style)

Parse the ignore file line by line. Rules for translating gitignore-style patterns to filesystem operations:

| Pattern form | Meaning | Action |
|---|---|---|
| `name/` (trailing `/`) | Directory only | `find -name name -type d -prune -exec rm -rf {} +` |
| `name` (no `/`) | File or dir, any depth | `find -name name -exec rm -rf {} +` |
| `path/to/thing` (contains `/`) | Anchored to root | `rm -rf "$STAGING/path/to/thing"` |
| `**/name/` | Name anywhere, dir only | Strip `**/`, then treat as `name/` |
| `*.ext` | Extension glob anywhere | `find -name '*.ext' -exec rm -rf {} +` |
| `/anchored` | Root-relative | Strip leading `/`, then `rm -rf "$STAGING/anchored"` |
| `# comment` or blank | Skip | — |

**Important:** Strip trailing `\r` from each line in case the ignore file has CRLF endings.

#### 2b. Sensitive files (mode 0600)

```bash
find "$STAGING" -type f -perm 0600 -delete
```

This catches files that are explicitly marked as sensitive (read/write owner only), regardless of whether they appear in the ignore file.

#### 2c. Clean up empty directories

After removing excluded files, prune empty directories bottom-up:

```bash
find "$STAGING" -mindepth 1 -type d -empty -delete
```

### Phase 3: Normalization

#### 3a. Permissions

The typical normalization scheme:

1. **Directories** → `0755`
2. **Files with any execute bit set** (`-perm /111`) → `0755`
3. **Files with a shebang** (`#!` in first two bytes) → `0755`
4. **All other regular files** → `0644`

Order matters: apply execute-bit and shebang rules first, then set the default for everything else.

```bash
find "$STAGING" -type d -exec chmod 0755 {} +
find "$STAGING" -type f -perm /111 -exec chmod 0755 {} +

# Shebang detection
while IFS= read -r -d '' f; do
    if [ "$(head -c2 "$f" 2>/dev/null)" = "#!" ]; then
        chmod 0755 "$f"
    fi
done < <(find "$STAGING" -type f -print0)

find "$STAGING" -type f ! -perm 0755 -exec chmod 0644 {} +
```

#### 3b. Line endings (CRLF → LF for text files only)

Use `file -b --mime-encoding` to detect text vs binary:

```bash
while IFS= read -r -d '' f; do
    enc=$(file -b --mime-encoding "$f")
    if [ "$enc" != "binary" ]; then
        sed -i 's/\r$//' "$f"
    fi
done < <(find "$STAGING" -type f -print0)
```

**Why this works:** `file --mime-encoding` returns `binary` for files containing null bytes or other binary indicators. Text files return encodings like `us-ascii`, `utf-8`, etc. The `sed 's/\r$//'` strips trailing CR characters, converting CRLF to LF.

**Pitfall:** Do NOT use `dos2unix` blindly — it may alter binary files or fail on files with mixed content. The `file` check is more reliable.

### Phase 4: Deterministic Archive Creation

```bash
rm -f "$OUT"

cd "$STAGING"
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

find . -print0 | LC_ALL=C sort -z | \
    tar --sort=name \
        --format=gnu \
        --owner=0 --group=0 --numeric-owner \
        --mtime="@$EPOCH" \
        --no-recursion \
        --null -T - \
        -cf - | \
    zstd -19 --long --no-check --single-thread --force -o "$OUT"
```

**Critical flags explained:**

| Flag | Purpose |
|---|---|
| `--sort=name` | Deterministic entry ordering within tar |
| `--format=gnu` | Use GNU tar format (consistent header layout) |
| `--owner=0 --group=0 --numeric-owner` | Normalize ownership to root:root numerically |
| `--mtime="@EPOCH"` | Set all entry timestamps to a fixed epoch value |
| `--no-recursion` | Don't recurse into directories (we provide the full file list) |
| `--null -T -` | Read NUL-delimited file list from stdin |
| `-cf -` | Write tar to stdout (pipe to compressor) |

**Symlinks:** Do NOT pass `-h` or `--dereference`. Default tar behavior preserves symlinks as symlinks.

**Compression:** `zstd -19 --long --no-check --single-thread --force` ensures deterministic output:
- `-19`: High compression level
- `--long`: Enable long-range mode for better compression
- `--no-check`: Omit content checksum (reduces output size; the tar itself is the integrity unit)
- `--single-thread`: Forces single-threaded mode for deterministic output (multi-threaded zstd may produce different output)
- `--force`: Overwrite existing output file (required for idempotent repeated runs when reading from stdin)

## Reproducibility Verification

Run the build twice and compare SHA-256 hashes. The script handles cleanup internally (via `rm -f "$OUT"`), so no manual removal is needed between runs:

```bash
bash build.sh
sha256sum release.tar.zst
# Run again — script removes old output automatically
bash build.sh
sha256sum release.tar.zst
# Hashes must match
```

## Common Pitfalls

1. **`tar -h` / `--dereference`** — Follows symlinks and archives the target file content. Never use this when symlinks must be preserved.

2. **Pattern matching scope** — GNU tar's `--exclude` uses fnmatch(3). A bare name like `*.tmp` matches at any depth. A path like `vendor/js` is anchored. When using `--no-recursion` with an explicit file list, you control what enters the archive, so exclusion happens at the file-list generation stage, not via tar flags.

3. **Empty directories after exclusion** — After deleting excluded files, directories may become empty. Prune them with `find -type d -empty -delete` to avoid shipping empty placeholder dirs.

4. **Binary file detection** — `file --mime-encoding` returning `binary` is the reliable indicator. Don't rely on file extensions alone (`.png` could be empty, `.dat` could be text).

5. **CRLF in the ignore file itself** — Always strip `\r` when reading `.distignore` lines.

6. **Special characters in filenames** — Use NUL-delimited (`-print0`, `--null`) pipelines throughout. Files with spaces, `$`, `!`, and other special chars must be handled correctly.

7. **Long paths** — GNU tar format handles long paths natively. The `--format=gnu` setting avoids POSIX header limitations.

8. **Writing to /app paths** — Use `task_shell` with heredocs to write files outside the workspace. The `write` tool only works within the workspace directory.

9. **Idempotency / repeated runs** — Test frameworks and CI systems run the build script multiple times in the same environment. `zstd` refuses to overwrite an existing output file when reading from stdin (a pipe), failing with: `zstd: /app/release.tar.zst already exists; stdin is an input - not proceeding`. Fix: always `rm -f "$OUT"` before the tar pipeline, and/or pass `--force` (`-f`) to zstd. This makes the script safe to run repeatedly without manual cleanup.

## Customization Points (Family Variation Axes)

These are the dimensions that vary across family members. When adapting this skill to a new task, read the task.yaml carefully for each:

### Source tree content and exclusions
- Directory names and structure
- Ignore file name and format (`.distignore`, `.gitignore`, etc.)
- Sensitive file permission threshold (0600 is common but may differ)
- Symlink types and targets

### Normalization rules
- Permission mapping (which files get which modes)
- Timestamp source (`SOURCE_DATE_EPOCH` env var, hardcoded default, or file-based)
- Text file detection method
- Line-ending target (LF is standard, but some variants may require CRLF)
- Owner/group policy (0:0 is standard for reproducible builds)

### Archive format and compression
- Tar format (`gnu`, `pax`, `ustar`)
- Compression algorithm (`zstd`, `gzip`, `xz`, `bzip2`)
- Compression flags (level, threading, checksum)
- Output path and naming convention
- Verification hash requirements

## Reference Implementation

See `scripts/build.sh` for a complete working implementation that was verified against the v01 task instance.
