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
a **bit-for-bit reproducible** compressed tarball. The script reads exclusion
rules from a `.distignore` file, normalizes metadata, and preserves symlinks.

## Step 0 — Extract Parameters From task.yaml (REQUIRED)

**Before writing any code**, read the `task.yaml` instruction and fill in these
parameters. Values in parentheses are the v01 defaults; your variant may differ.

| Parameter | Variable | Where to find it | v01 default |
|---|---|---|---|
| Source tree root | `SRC` | "source tree already exists at …" | `/app/src` |
| Output archive path | `OUT` | "produces …" | `/app/release.tar.zst` |
| Ignore file name | `IGNORE` | "Read exclusion rules from …" | `$SRC/.distignore` |
| Default epoch | `DEFAULT_EPOCH` | "otherwise …" | `946684800` |
| Sensitive file mode | `SENS_MODE` | "exclude any file whose mode is exactly …" | `0600` |
| Dir permission | `DIR_MODE` | "directories: …" | `0755` |
| Exec file permission | `EXEC_MODE` | "files with a shebang or execute permission: …" | `0755` |
| Regular file permission | `FILE_MODE` | "all other regular files: …" | `0644` |
| Tar format | `TAR_FMT` | "Use … tar format" | `gnu` |
| Zstd flags | `ZSTD_FLAGS` | "Compress with \`zstd …\`" | `-19 --long --no-check --single-thread` |
| Archive owner:group | `OWNER`/`GROUP` | "Set archive owner and group to numeric …" | `0` / `0` |
| Line-ending policy | — | "Normalize line endings to …" | `LF` for text files |
| Text detection method | — | inferred from task | `file -b` contains "text" |

## Idempotency — The #1 Failure Mode

The script **must** be safe to run multiple times without cleanup between runs.

```
zstd: /app/release.tar.zst already exists; stdin is an input - not proceeding.
```

**Required fixes** (use BOTH):
1. `rm -f "$OUT"` before the `tar | zstd` pipeline.
2. `--force` flag on zstd so it overwrites even if step 1 somehow misses.

## Complete Reference Script

Copy this script to `/app/build.sh` and `chmod +x` it. **Replace the parameter
block** with values from your task.yaml. The pipeline below is invariant.

```bash
#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

# ═══ PARAMETERS — adapt these to match your task.yaml ═══════════
SRC="/app/src"                         # source tree root
OUT="/app/release.tar.zst"             # output archive path
IGNORE="$SRC/.distignore"              # ignore-file location
DEFAULT_EPOCH=946684800                # fallback timestamp
SENS_MODE=0600                         # sensitive file mode to exclude
DIR_MODE=0755                          # target directory permission
EXEC_MODE=0755                         # target permission for exec/shebang files
FILE_MODE=0644                         # target permission for other files
TAR_FMT=gnu                            # tar format (gnu or posix)
OWNER=0                                # archive owner (numeric)
GROUP=0                                # archive group (numeric)
ZSTD_FLAGS="-19 --long --no-check --single-thread"
# ════════════════════════════════════════════════════════════════

EPOCH="${SOURCE_DATE_EPOCH:-$DEFAULT_EPOCH}"

STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# ── 1. Copy source tree preserving symlinks ────────────────────────
cp -a --no-dereference "$SRC"/. "$STAGING"/
cd "$STAGING"

# ── 2. Apply .distignore exclusions (skip if file absent) ─────────
if [[ -f "$IGNORE" ]]; then
  # Copy ignore file into staging so we can read it after cd
  cp "$IGNORE" ./.distignore_local 2>/dev/null || true
  while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    # Strip trailing whitespace and CR
    pattern="${pattern%$'\r'}"
    pattern="${pattern%"${pattern##*[![:space:]]}"}"
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
  done < .distignore_local
  rm -f .distignore_local
fi

# ── 3. Exclude files with the sensitive mode ──────────────────────
find . -type f -perm "$SENS_MODE" -delete 2>/dev/null || true

# ── 4. Normalize line endings for text files only ─────────────────
while IFS= read -r -d '' f; do
    # Skip symlinks (find -type f already excludes them, but be safe)
    [[ -L "$f" ]] && continue
    if file -b "$f" | grep -qi 'text'; then
        sed -i 's/\r$//' "$f"
    fi
done < <(find . -type f -print0)

# ── 5. Normalize permissions ──────────────────────────────────────
find . -type d -exec chmod "$DIR_MODE" {} +

while IFS= read -r -d '' f; do
    if head -c 2 "$f" 2>/dev/null | grep -q '^#!'; then
        chmod "$EXEC_MODE" "$f"
    elif [[ "$(stat -c '%A' "$f")" == *x* ]]; then
        chmod "$EXEC_MODE" "$f"
    else
        chmod "$FILE_MODE" "$f"
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
    --format="$TAR_FMT" \
    --numeric-owner \
    --owner="$OWNER" \
    --group="$GROUP" \
    --mtime="@${EPOCH}" \
  | zstd $ZSTD_FLAGS --force -o "$OUT"

rm -f /tmp/_tar_manifest.txt
```

## Decision Rules

### Staging Copy (Step 1)

- `cp -a` preserves attributes; `--no-dereference` keeps symlinks as symlinks.
- Work on a copy so the original source tree is never modified.
- `mktemp -d` + `trap` ensures cleanup even on failure.

### `.distignore` Parsing (Step 2)

Four pattern types are handled in this priority order:

| Pattern shape | Example | Action |
|---|---|---|
| `**/name/` | `**/__pycache__/` | `find -depth -type d -name "name" -exec rm -rf {} +` |
| `path/` | `.hg/` `vendor/js/` | `rm -rf "./path"` |
| `*.ext` glob | `*.tmp` `*.pyc` | `find \( -type f -o -type l \) -name "*.ext" -delete` |
| literal | `secrets/key` | `rm -f "./literal"` |

**Critical bash pitfall**: Use `"**/"*"/"` (quoted literal `**/`) to detect the
recursive-directory pattern. Using `**/*/` without quotes lets bash treat `**`
as a glob wildcard, causing false matches like `vendor/js/`.

**Robustness**: Guard with `if [[ -f "$IGNORE" ]]` — some variants may omit
the ignore file. Strip trailing whitespace from patterns to handle editor-added
spaces.

### Sensitive Mode Exclusion (Step 3)

`find . -type f -perm "$SENS_MODE"` — without a prefix (`/` or `-`), `-perm`
is an **exact** match. The mode value comes from the task description.

### Text Detection & Line Endings (Step 4)

`file -b "$f" | grep -qi 'text'` correctly classifies:
- `ASCII text`, `C source`, `with CRLF line terminators` → **text** ✓
- `PNG image data`, `data` (null bytes), `empty` → **not text** ✓

`sed -i 's/\r$//'` strips trailing CR; no-op on files already LF.
An explicit `[[ -L "$f" ]] && continue` guards against symlink edge cases.

### Permissions (Step 5)

| Entry type | Target mode | Detection |
|---|---|---|
| Directory | `$DIR_MODE` | `find -type d` |
| File with shebang | `$EXEC_MODE` | `head -c 2 \| grep '^#!'` |
| File with any exec bit | `$EXEC_MODE` | `stat -c '%A'` contains `x` |
| All other files | `$FILE_MODE` | default fallback |

Symlinks are excluded because `find -type f` skips `-type l`.

### Sorted Manifest + Tar + Zstd (Step 6)

- `find . -print0 | sort -z` — null-delimited, LC_ALL=C sorted.
- `--no-recursion --null --files-from=...` — add exactly listed entries.
- `--format="$TAR_FMT"` — `gnu` or `posix` per task description.
- `--numeric-owner --owner=$OWNER --group=$GROUP` — from task description.
- `--mtime="@EPOCH"` — override mtime for all entries including symlinks.
- `rm -f "$OUT"` + `zstd --force` — overwrite protection for idempotency.
- `--single-thread` in zstd flags — required for bit-for-bit reproducibility.

## Verification Checklist

After building the archive, verify:

1. **Idempotent**: Run `build.sh` twice back-to-back — second run must succeed.
2. **Exclusions**: `tar tf` output must not contain ignore-matched paths or
   sensitive-mode files.
3. **Permissions**: correct per task description.
4. **Symlinks**: `lrwxrwxrwx ... -> target` (not dereferenced).
5. **Owner/Group**: correct numeric values per task description.
6. **Mtime**: uniform timestamp on all entries.
7. **Line endings**: extracted text files have correct endings per task.
8. **Binary files**: byte-identical to originals.
9. **Reproducibility**: same `SOURCE_DATE_EPOCH` → identical hash.

## Common Pitfalls

| Pitfall | Impact | Fix |
|---|---|---|
| **No `rm -f "$OUT"` / `--force` before zstd** | 2nd run fails | `rm -f "$OUT"` + `--force` |
| Hardcoding v01 paths instead of reading task.yaml | Wrong SRC/OUT/IGNORE | Extract params in Step 0 |
| Bash glob `**/*/` matches `vendor/js/` | Wrong files excluded | Quote: `"**/"*"/"` |
| Missing `LC_ALL=C` | Sort order varies | Export at script top |
| Missing `.distignore` guard | Script fails if file absent | `if [[ -f "$IGNORE" ]]` |
| `sed` on binary files | Corrupts data | Check `file -b` for `text` first |
| `chmod` on symlinks | May change target | `find -type f` skips symlinks |
| Multi-threaded zstd | Non-deterministic | Always `--single-thread` |
| `cp -a` without `--no-dereference` | Symlinks become files | Add `--no-dereference` |
| Trailing whitespace in .distignore | Patterns don't match | Strip with `${pattern%"${pattern##*[![:space:]]}"}` |

## Invariant Pipeline vs Variant Parameters

**These steps are the same for every variant:**
- Staging copy with `cp -a --no-dereference`
- Pattern-based exclusion parsing (4 types)
- Text detection via `file -b`
- Shebang detection via `head -c 2`
- Null-delimited sorted manifest with `find -print0 | sort -z`
- Tar with `--no-recursion --null --files-from`
- Zstd with `--force` and `--single-thread`
- `rm -f "$OUT"` for idempotency

**These values come from task.yaml and MUST be adapted:**
- `SRC`, `OUT`, `IGNORE` paths
- `DEFAULT_EPOCH` fallback timestamp
- `SENS_MODE` sensitive file mode
- `DIR_MODE`, `EXEC_MODE`, `FILE_MODE` permission targets
- `TAR_FMT` tar format
- `OWNER`/`GROUP` numeric IDs
- `ZSTD_FLAGS` compression flags
