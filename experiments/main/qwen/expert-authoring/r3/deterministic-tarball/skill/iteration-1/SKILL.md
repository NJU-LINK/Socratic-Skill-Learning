---
name: deterministic-tarball
description: >
  Build a deterministic release packaging script that reads exclusion rules
  from a .distignore file, normalizes permissions/line-endings/timestamps,
  preserves symlinks, and produces a bit-for-bit reproducible tar.zst archive.
---

# Deterministic Tarball — Release Packaging Skill

## Goal

Create an executable `build.sh` that takes an existing source tree and produces
a **bit-for-bit reproducible** compressed tarball (`release.tar.zst`).

## High-Level Strategy

```
source tree  →  staging copy  →  exclude  →  normalize  →  tar  →  zstd  →  output
```

1. **Copy** the source tree into a temporary staging directory (preserving symlinks).
2. **Exclude** paths matched by `.distignore` and files with mode `0600`.
3. **Normalize** line endings (CRLF→LF for text files) and permissions.
4. **Archive** with GNU tar using a sorted manifest, fixed owner/group/mtime.
5. **Compress** with deterministic zstd flags.
6. **Clean up** the staging directory.

## Step-by-Step Decision Rules

### 1. Staging Copy

```bash
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT
cp -a --no-dereference "$SRC"/. "$STAGING"/
cd "$STAGING"
```

- `cp -a` preserves attributes; `--no-dereference` keeps symlinks as symlinks.
- Work on the copy so the original source tree is never modified.

### 2. Parse and Apply `.distignore`

Read the `.distignore` file line-by-line. Each line is one of four pattern types:

| Pattern shape             | Meaning                                    | Action                                              |
|---------------------------|--------------------------------------------|-----------------------------------------------------|
| `**/dirname/`             | Recursive directory match anywhere         | `find . -depth -type d -name "dirname" -exec rm -rf {} +` |
| `path/to/dir/`            | Root-relative directory path               | `rm -rf "./path/to/dir"`                            |
| `*.ext` or glob           | Filename glob matched anywhere             | `find . \( -type f -o -type l \) -name "*.ext" -delete` |
| `exact/path`              | Exact file path relative to root           | `rm -f "./exact/path"`                              |

**Critical bash pitfall**: Use `"**/"*"/"` (with quoted literal `**/`) to detect
the recursive-directory pattern. Using `**/*/` without quotes lets bash treat
`**` as a glob wildcard, causing false matches like `vendor/js/`.

```bash
while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    pattern="${pattern%$'\r'}"          # strip CR (handle CRLF ignore files)
    [[ -z "$pattern" || "$pattern" == \#* ]] && continue

    if [[ "$pattern" == "**/"*"/" ]]; then
        d="${pattern#\*\*/}"; d="${d%/}"
        find . -depth -type d -name "$d" -exec rm -rf {} + 2>/dev/null || true
    elif [[ "$pattern" == */ ]]; then
        rm -rf "./${pattern%/}" 2>/dev/null || true
    elif [[ "$pattern" == *[\*\?]* ]]; then
        find . \( -type f -o -type l \) -name "$pattern" -delete 2>/dev/null || true
    else
        rm -f "./$pattern" 2>/dev/null || true
    fi
done < .distignore
```

### 3. Exclude Mode-0600 Files

```bash
find . -type f -perm 0600 -delete 2>/dev/null || true
```

`-perm 0600` without prefix is an **exact** match (only mode 0600, not 0644 etc.).

### 4. Normalize Line Endings (Text Files Only)

**Text detection**: Use `file -b` and check for the word `text` (case-insensitive).
This correctly classifies:
- `ASCII text`, `C source, ASCII text`, `with CRLF line terminators` → text ✓
- `PNG image data`, `data` (null bytes), `empty` → not text ✓

```bash
while IFS= read -r -d '' f; do
    if file -b "$f" | grep -qi 'text'; then
        sed -i 's/\r$//' "$f"
    fi
done < <(find . -type f -print0)
```

- Process substitution `< <(find ...)` avoids subshell variable-scope issues.
- `sed -i 's/\r$//'` strips trailing CR (CRLF → LF); no-op on files already LF.
- Binary files (images, compiled objects, files with null bytes) are left untouched.

### 5. Normalize Permissions

| Entry type                        | Target mode |
|-----------------------------------|-------------|
| Directory                         | `0755`      |
| File with shebang (`#!` prefix)   | `0755`      |
| File with any execute bit set     | `0755`      |
| All other regular files           | `0644`      |

```bash
find . -type d -exec chmod 0755 {} +

while IFS= read -r -d '' f; do
    if head -c 2 "$f" 2>/dev/null | grep -q '^#!'; then
        chmod 0755 "$f"
    elif [[ "$(stat -c '%A' "$f")" == *x* ]]; then
        chmod 0755 "$f"
    else
        chmod 0644 "$f"
    fi
done < <(find . -type f -print0)
```

- `head -c 2` reads just the first two bytes for shebang detection.
- `stat -c '%A'` returns the human-readable permission string; `*x*` catches any execute bit.
- Symlinks are **not** touched (find uses `-type f`, excluding `-type l`).

### 6. Build Sorted Manifest and Create Tarball

```bash
export LC_ALL=C    # critical: deterministic sort order
find . -print0 | sort -z > /tmp/_tar_manifest.txt

tar --create \
    --no-recursion \
    --null \
    --files-from=/tmp/_tar_manifest.txt \
    --format=gnu \
    --numeric-owner \
    --owner=0 \
    --group=0 \
    --mtime="@${EPOCH}"
```

Key flags:
- `--no-recursion` + `--files-from` = add exactly the listed entries, no traversal.
- `--format=gnu` = GNU tar format (magic `ustar  \0` at offset 257).
- `--numeric-owner --owner=0 --group=0` = root ownership in archive.
- `--mtime="@EPOCH"` = override mtime for **all** entries (including symlinks).
- `LC_ALL=C` ensures identical sort order across locales.

### 7. Compress with Deterministic zstd

```bash
| zstd -19 --long --no-check --single-thread -o "$OUT"
```

- `-19` = maximum compression level.
- `--long` = long-distance matching for repetitive content.
- `--no-check` = disable content checksum (avoids any non-determinism).
- `--single-thread` = single-threaded mode (required for reproducibility).

### 8. Timestamp Handling

```bash
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"
```

Use `SOURCE_DATE_EPOCH` environment variable if set; otherwise fall back to
`946684800` (2000-01-01 00:00:00 UTC).

## Verification Checklist

After building the archive, verify:

1. **Exclusions**: `tar tf archive.tar.zst` should not contain `.distignore`-matched
   paths or mode-0600 files.
2. **Permissions**: Directories `drwxr-xr-x`, shebang/exec files `-rwxr-xr-x`,
   others `-rw-r--r--`.
3. **Symlinks**: Appear as `lrwxrwxrwx ... -> target` (not dereferenced).
4. **Owner/Group**: All entries show `0/0`.
5. **Mtime**: All entries show the same timestamp.
6. **Line endings**: Extracted text files have LF only (no `0d 0a`).
7. **Binary files**: Extracted binary files are byte-identical to originals.
8. **Reproducibility**: Running twice with the same `SOURCE_DATE_EPOCH` produces
   identical MD5/SHA256 hashes.

## Common Pitfalls

| Pitfall | Consequence | Fix |
|---------|-------------|-----|
| Bash glob `**/*/` matches `vendor/js/` | Wrong files excluded | Quote literal prefix: `"**/"*"/"` |
| Missing `LC_ALL=C` | Sort order varies by locale | Export at script top |
| `sed` on binary files | Corrupts binary data | Check `file -b` for `text` first |
| `chmod` on symlinks | May change target or fail | Use `find -type f` to skip symlinks |
| Multi-threaded zstd | Non-deterministic output | Always use `--single-thread` |
| `cp -a` without `--no-dereference` | Symlinks become regular files | Add `--no-dereference` explicitly |
| Forgetting to strip `\r` from `.distignore` patterns | Patterns don't match | `pattern="${pattern%$'\r'}"` |
| Using `--sort=name` with `--files-from` | May conflict; redundant | Pre-sort manifest, omit `--sort=name` |

## Adaptation to Variant Dimensions

When the task varies along the spec axes:

- **source_tree_content_and_exclusions**: The `.distignore` parser handles any
  combination of directory paths, recursive `**/` patterns, filename globs, and
  exact paths. Mode-0600 exclusion is independent of content.

- **normalization_rules**: If permission rules change (e.g., different target
  modes), adjust the chmod section. If timestamp source changes, modify the
  `EPOCH` assignment. If text-file detection criteria change, adapt the
  `file -b | grep` filter.

- **archive_format_and_compression**: If tar format or compression changes,
  swap `--format=gnu` and zstd flags accordingly. The staging/normalization
  pipeline remains identical.
