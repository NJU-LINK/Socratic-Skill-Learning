---
name: deterministic-tarball
description: >
  Build bit-for-bit reproducible release archives from a source tree.
  Implements a four-phase pipeline (enumerate → stage → normalize → archive+compress)
  that handles .distignore/gitignore-style exclusions, 0600-mode file exclusion,
  permission normalization, line-ending normalization for text files, symlink
  preservation, and deterministic GNU tar + zstd compression.
---

# Deterministic Tarball Packaging

## Overview

This skill produces bit-for-bit reproducible `.tar.zst` release archives from an
existing source tree. The same inputs (source tree + `SOURCE_DATE_EPOCH`) always
yield the identical output byte sequence.

## Architecture: Four-Phase Pipeline

```
┌─────────────┐    ┌──────────┐    ┌────────────┐    ┌────────────────┐
│  Enumerate   │───▶│  Stage   │───▶│ Normalize  │───▶│ Archive+Compress│
│  + Exclude   │    │  (copy)  │    │ perms+eol  │    │ tar | zstd     │
└─────────────┘    └──────────┘    └────────────┘    └────────────────┘
```

### Why staging?

Staging into a temporary directory is strongly preferred over inline tar
manipulation because:
- File content must be mutated (CRLF→LF) without touching the original tree
- Permissions must be detected *before* normalization (shebang/exec check)
- Exclusions must be applied cleanly before archiving
- The staging dir is disposable (`trap 'rm -rf "$STAGING"' EXIT`)

---

## Phase 1: Enumerate & Exclude

### .distignore Parsing (gitignore-style semantics)

The `.distignore` file uses gitignore-like pattern rules. Key semantics:

| Pattern | Meaning |
|---------|---------|
| `# ...` | Comment (ignored) |
| `name/` | Directory-only match; trailing `/` stripped for matching |
| `!pattern` | Negation — re-include a previously excluded path |
| `pattern` (no `/`) | Match against **basename** at any depth |
| `path/pattern` (has `/`) | **Anchored** — match against full relative path |
| `**/` | Match zero or more directory components |
| `*` | Match anything except `/` |
| `?` | Match single character except `/` |

**Implementation approach** (Python recommended for correctness):

```python
def parse_distignore(path):
    patterns = []
    for line in open(path):
        line = line.rstrip('\n\r')
        if not line or line.startswith('#'): continue
        negate = line.startswith('!'); line = line.lstrip('!')
        dir_only = line.endswith('/'); line = line.rstrip('/')
        anchored = line.startswith('/') or '/' in line
        line = line.lstrip('/')
        regex = glob_to_regex(line)  # * → [^/]*, ** → .*, etc.
        patterns.append(dict(regex=regex, negate=negate,
                             dir_only=dir_only, anchored=anchored))
    return patterns

def is_ignored(relpath, is_dir, patterns):
    result = False
    for pat in patterns:
        if pat['dir_only'] and not is_dir: continue
        if pat['anchored']:
            matched = pat['regex'].fullmatch(relpath)
        else:
            matched = pat['regex'].fullmatch(relpath.rsplit('/',1)[-1])
        if matched:
            result = not pat['negate']
    return result
```

**Critical gotcha**: Non-anchored patterns (no `/` except trailing) match the
**basename** at any depth. `*.tmp` must exclude `foo/bar/baz.tmp`, not just
`baz.tmp` at the root.

### 0600-Mode File Exclusion

Any regular file whose permission bits are exactly `0600` is excluded, even if
not listed in `.distignore`. This catches sensitive files (private keys,
credentials). Symlinks and directories are NOT subject to this rule.

```python
mode = os.stat(filepath).st_mode & 0o777
if mode == 0o600:
    skip()
```

### Tree Walking

Use a recursive walk (not `os.walk` with `followlinks`) to:
1. Check each entry against exclusion rules
2. If a **directory** is excluded → skip it and everything beneath it
3. If a **file** is excluded → skip it
4. Symlinks → check `.distignore` only (not 0600); preserve as symlinks
5. Copy surviving entries to the staging directory

---

## Phase 2: Stage (Copy to Temp Directory)

```bash
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT
```

- **Regular files**: `shutil.copy2(src, dst)` or `cp` — preserves content
- **Directories**: `os.makedirs` or `mkdir -p`
- **Symlinks**: `os.readlink` + `os.symlink` — preserves link target exactly
  (do NOT use `cp -a` for symlinks as it may dereference in some contexts)

---

## Phase 3: Normalize

### Permission Normalization

**Order matters**: detect shebang/execute on the staged copy *before* changing
any permissions.

```
For each regular file in staging:
  1. Check if ANY execute bit is set  →  -x test or stat
  2. Check if first 2 bytes are '#!'   →  head -c2 | grep '^#!'
  3. If either → chmod 0755
  4. Otherwise  → chmod 0644

For each directory in staging:
  → chmod 0755
```

### Line-Ending Normalization

Only modify **text** files; keep binary files byte-identical.

**Detection**: `file --mime-type -b "$filepath"` — treat any result starting
with `text/` as text. Common text MIME types: `text/plain`, `text/x-c`,
`text/x-script.python`, `text/x-shellscript`.

**Conversion**: `sed -i 's/\r$//' "$file"` — strips trailing CR before each LF,
converting CRLF → LF. This is safe because:
- On already-LF files, `\r$` never matches → no change
- On binary files, we skip entirely (not `text/*`)

---

## Phase 4: Archive + Compress

### Deterministic tar Command

```bash
MTIME="${SOURCE_DATE_EPOCH:-946684800}"

# Generate sorted null-delimited file list
(cd "$STAGING" && find . -mindepth 1 -print0 | sort -z) > "$FILELIST"

tar --create --file=- \
    --directory="$STAGING" \
    --sort=name \
    --owner=0:0 --group=0:0 \
    --mtime="@${MTIME}" \
    --format=gnu \
    --null --no-recursion --files-from="$FILELIST" \
  | zstd -19 --long --no-check --single-thread \
    > "$OUT"
```

### Flag Rationale

| Flag | Purpose |
|------|---------|
| `--sort=name` | Deterministic entry ordering (secondary to explicit file list sort) |
| `--owner=0:0 --group=0:0` | Numeric zero ownership; name="0", uid/gid=0 |
| `--mtime="@${MTIME}"` | All entries get the same timestamp; `@` = epoch seconds |
| `--format=gnu` | GNU tar format (not POSIX/PAX) — required by spec |
| `--null --files-from` | Null-delimited input for safe special-character handling |
| `--no-recursion` | Tar adds only listed entries; no filesystem-order leakage |
| `--directory="$STAGING"` | Paths in archive are relative to staging root |

### Deterministic zstd Compression

```
zstd -19 --long --no-check --single-thread
```

| Flag | Purpose |
|------|---------|
| `-19` | Maximum compression level |
| `--long` | Enable long-distance matching |
| `--no-check` | Omit content checksum from frame (avoids non-determinism) |
| `--single-thread` | Single-threaded for deterministic output |

---

## Edge Cases & Robustness

### Special Filenames
- **Spaces**: `file with spaces.txt` — handled by null-delimited pipelines
  (`-print0`, `sort -z`, `--null`, `-0`)
- **Shell metacharacters**: `file$special\!chars.py` — null-delimited pipelines
  avoid shell interpretation
- **Very long names** (>200 chars): GNU tar handles via extended headers

### Deep Nesting
- 30+ levels of nesting — no issue for Python recursion (limit=1000) or tar
- Each level is a separate directory entry in the archive

### Symlinks
- Preserved as symlinks (never dereferenced)
- Both relative (`../docs/README.txt`) and absolute (`/etc/passwd`) targets work
- `tar` does not follow symlinks by default (do NOT use `-h`/`--dereference`)

### Empty Directories
- Parent directories of excluded entries remain if not themselves excluded
- Example: `vendor/js/` excluded but `vendor/` stays as empty directory

### Reproducibility Guarantees
- No filesystem timestamps leak into the archive (`--mtime` overrides all)
- No user/group name variation (`--owner=0:0 --group=0:0`)
- Deterministic sort order (`find | sort` + `--sort=name`)
- Deterministic compression (`--single-thread --no-check`)
- Same `SOURCE_DATE_EPOCH` → identical output bytes

---

## Adaptation Guide for Variants

When the spec varies these dimensions, adjust accordingly:

| Dimension | What Changes |
|-----------|-------------|
| **Source tree content** | Different exclusion patterns, file types, symlink targets |
| **Normalization rules** | Different permission thresholds, timestamp sources, text detection heuristics, line-ending targets (e.g., CRLF output) |
| **Archive format** | Different tar format (`--format=posix`/`pax`), compression tool/level, output path |

The four-phase pipeline structure remains the same; only the details within
each phase change.
