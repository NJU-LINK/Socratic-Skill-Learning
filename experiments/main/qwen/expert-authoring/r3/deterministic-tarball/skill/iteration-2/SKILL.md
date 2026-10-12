---
name: deterministic-tarball
description: >
  Build a deterministic release packaging script that reads exclusion rules
  from a .distignore file, normalizes permissions/line-endings/timestamps,
  preserves symlinks, and produces a bit-for-bit reproducible tar.zst archive.
---

# Deterministic Tarball — Release Packaging Skill

## Goal

Create an executable `build.sh` that takes an existing source tree at `/app/src`
and produces a **bit-for-bit reproducible** compressed tarball at
`/app/release.tar.zst`.

## Idempotency — The #1 Failure Mode

The script **must** be safe to run multiple times in the same process without
the test harness cleaning up between runs. The single most common failure is:

```
zstd: /app/release.tar.zst already exists; stdin is an input - not proceeding.
```

**Required fixes** (use BOTH for defense-in-depth):

1. `rm -f "$OUT"` before the `tar | zstd` pipeline.
2. `--force` flag on zstd so it overwrites even if step 1 somehow misses.

Without both, the second test run will always fail.

## Complete Reference Script

Copy this script verbatim to `/app/build.sh` and `chmod +x` it. This is a
self-contained, tested solution — not a skeleton or template.

```bash
#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

SRC="/app/src"
OUT="/app/release.tar.zst"
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"

STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# ── 1. Copy source tree preserving symlinks ────────────────────────
cp -a --no-dereference "$SRC"/. "$STAGING"/
cd "$STAGING"

# ── 2. Apply .distignore exclusions ───────────────────────────────
while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    pattern="${pattern%$'\r'}"
    [[ -z "$pattern" || "$pattern" == \#* ]] && continue

    if [[ "$pattern" == "**/"*"/" ]]; then
        # Recursive directory: **/__pycache__/
        d="${pattern#\*\*/}"; d="${d%/}"
        find . -depth -type d -name "$d" -exec rm -rf {} + 2>/dev/null || true
    elif [[ "$pattern" == */ ]]; then
        # Root-relative directory: .hg/  vendor/js/
        rm -rf "./${pattern%/}" 2>/dev/null || true
    elif [[ "$pattern" == *[\*\?]* ]]; then
        # Filename glob: *.tmp  *.pyc …
        find . \( -type f -o -type l \) -name "$pattern" -delete 2>/dev/null || true
    else
        # Exact file path
        rm -f "./$pattern" 2>/dev/null || true
    fi
done < .distignore

# ── 3. Exclude files whose mode is exactly 0600 ───────────────────
find . -type f -perm 0600 -delete 2>/dev/null || true

# ── 4. Normalize line endings (CRLF → LF) for text files only ─────
while IFS= read -r -d '' f; do
    if file -b "$f" | grep -qi 'text'; then
        sed -i 's/\r$//' "$f"
    fi
done < <(find . -type f -print0)

# ── 5. Normalize permissions ──────────────────────────────────────
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

# ── 6. Build sorted manifest and create tarball ───────────────────
find . -print0 | sort -z > /tmp/_tar_manifest.txt

# CRITICAL: remove previous output so zstd never refuses to overwrite
rm -f "$OUT"

tar --create \
    --no-recursion \
    --null \
    --files-from=/tmp/_tar_manifest.txt \
    --format=gnu \
    --numeric-owner \
    --owner=0 \
    --group=0 \
    --mtime="@${EPOCH}" \
  | zstd -19 --long --no-check --single-thread --force -o "$OUT"

rm -f /tmp/_tar_manifest.txt
```

## Decision Rules (Why Each Step Works)

### Staging Copy (Step 1)

- `cp -a` preserves attributes; `--no-dereference` keeps symlinks as symlinks.
- Work on the copy so the original source tree is never modified.
- `mktemp -d` + `trap` ensures cleanup even on failure.

### `.distignore` Parsing (Step 2)

Four pattern types are handled in this order:

| Pattern shape | Example | Meaning | Action |
|---|---|---|---|
| `**/name/` | `**/__pycache__/` | Recursive dir match | `find -depth -type d -name "name" -exec rm -rf {} +` |
| `path/` | `.hg/` `vendor/js/` | Root-relative dir | `rm -rf "./path"` |
| glob | `*.tmp` `*.pyc` | Filename glob | `find \( -type f -o -type l \) -name "glob" -delete` |
| literal | `secrets/key` | Exact file | `rm -f "./literal"` |

**Critical bash pitfall**: Use `"**/"*"/"` (quoted literal `**/`) to detect the
recursive-directory pattern. Using `**/*/` without quotes lets bash treat `**`
as a glob wildcard, causing false matches like `vendor/js/`.

### Mode-0600 Exclusion (Step 3)

`find . -type f -perm 0600` — without a prefix (`/` or `-`), `-perm 0600` is an
**exact** match (only mode 0600, not 0644 etc.).

### Text Detection & Line Endings (Step 4)

`file -b "$f" | grep -qi 'text'` correctly classifies:
- `ASCII text`, `C source`, `with CRLF line terminators` → **text** ✓
- `PNG image data`, `data` (null bytes), `empty` → **not text** ✓

`sed -i 's/\r$//'` strips trailing CR; no-op on files already LF.

### Permissions (Step 5)

| Entry type | Target mode | Detection |
|---|---|---|
| Directory | 0755 | `find -type d` |
| File with shebang | 0755 | `head -c 2 \| grep '^#!'` |
| File with any exec bit | 0755 | `stat -c '%A'` contains `x` |
| All other files | 0644 | default fallback |

Symlinks are excluded because `find -type f` skips `-type l`.

### Sorted Manifest + Tar + Zstd (Step 6)

- `find . -print0 | sort -z` produces a null-delimited, LC_ALL=C sorted manifest.
- `--no-recursion --null --files-from=...` adds exactly the listed entries.
- `--format=gnu` — GNU tar format.
- `--numeric-owner --owner=0 --group=0` — root ownership.
- `--mtime="@EPOCH"` — override mtime for all entries including symlinks.
- `rm -f "$OUT"` before pipeline — prevents zstd overwrite refusal.
- `zstd --force` — second layer of overwrite protection.
- `--single-thread --no-check` — required for bit-for-bit reproducibility.

### Timestamp

```bash
EPOCH="${SOURCE_DATE_EPOCH:-946684800}"
```

Uses `SOURCE_DATE_EPOCH` when set; otherwise `946684800` (2000-01-01 UTC).

## Verification Checklist

After building the archive:

1. **Idempotent**: Run `build.sh` twice back-to-back — second run must succeed.
2. **Exclusions**: `tar tf` output must not contain `.distignore`-matched paths
   or mode-0600 files.
3. **Permissions**: dirs `drwxr-xr-x`, shebang/exec `-rwxr-xr-x`,
   others `-rw-r--r--`.
4. **Symlinks**: `lrwxrwxrwx ... -> target` (not dereferenced).
5. **Owner/Group**: all `0/0`.
6. **Mtime**: uniform timestamp on all entries.
7. **Line endings**: extracted text files have LF only.
8. **Binary files**: byte-identical to originals.
9. **Reproducibility**: same `SOURCE_DATE_EPOCH` → identical hash.

## Common Pitfalls

| Pitfall | Impact | Fix |
|---|---|---|
| **No `rm -f "$OUT"` / `--force` before zstd** | 2nd run fails: `already exists` | `rm -f "$OUT"` + `--force` on zstd |
| Bash glob `**/*/` matches `vendor/js/` | Wrong files excluded | Quote: `"**/"*"/"` |
| Missing `LC_ALL=C` | Sort order varies by locale | Export at script top |
| `sed` on binary files | Corrupts binary data | Check `file -b` for `text` first |
| `chmod` on symlinks | May change target or fail | `find -type f` skips symlinks |
| Multi-threaded zstd | Non-deterministic output | Always `--single-thread` |
| `cp -a` without `--no-dereference` | Symlinks become files | Add `--no-dereference` |
| Forgetting `\r` in `.distignore` | Patterns don't match | `pattern="${pattern%$'\r'}"` |

## Adaptation to Variant Dimensions

- **source_tree_content_and_exclusions**: The `.distignore` parser handles any
  combination of dir paths, `**/` patterns, globs, and exact paths. Mode-0600
  exclusion is independent of content.

- **normalization_rules**: If permission targets change, adjust the chmod
  section. If timestamp source changes, modify `EPOCH`. If text detection
  criteria change, adapt the `file -b | grep` filter.

- **archive_format_and_compression**: If tar format or compression changes,
  swap `--format=gnu` and zstd flags. The staging/normalization pipeline
  stays identical.
