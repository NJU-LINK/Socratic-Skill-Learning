---
name: deterministic-tarball
description: >
  Build bit-for-bit reproducible tar archives from a source tree with metadata
  normalization (permissions, line endings, mtimes, ownership), content-based
  exclusion rules, and deterministic compression. Handles symlinks, deep
  nesting, long paths, special characters, binary/text distinction, and
  gitignore-style exclusion patterns.
---

# Deterministic Tarball Packaging

## Overview

This skill produces a byte-identical compressed tar archive from a source tree,
regardless of the host environment's timestamps, user IDs, or file ordering. The
approach uses a **staging directory** to normalize content and metadata before
archiving, because GNU tar cannot modify file contents (e.g., line endings) or
apply per-file permission logic on the fly.

## Architecture: Staging Directory Pattern

```
source tree → exclusion filter → staging dir → normalize perms → normalize line endings → tar | compress → output
```

### Why staging is required

- **Line ending normalization** (CRLF→LF) requires rewriting file contents; tar
  cannot do this during archive creation.
- **Permission normalization** requires per-file decisions (shebang detection,
  execute-bit checks) that are easier to apply in a working copy.
- **Exclusion filtering** with gitignore-style patterns is simpler when you
  control the copy step than when using tar's `--exclude` (which uses fnmatch
  where `*` does not cross `/`).

## Step-by-step Method

### 1. Parse exclusion rules

Read the ignore file (typically `.distignore` or similar). Classify each
non-empty, non-comment line into one of four categories:

| Pattern form | Meaning | Matching strategy |
|---|---|---|
| `name/` | Root-level directory | `relpath == "name"` or `relpath starts with "name/"` |
| `path/to/dir/` | Root-level nested directory | `relpath == "path/to/dir"` or `relpath starts with "path/to/dir/"` |
| `**/name/` | Directory at any depth | Check if `"/$relpath/"` contains `"/name/"` |
| `**/*.ext` | File glob at any depth | Match pattern against basename at any depth |
| `*.ext` | File glob (root level) | Match against basename using shell `case` glob |

Additional exclusion criteria (e.g., file mode 0600) are checked alongside
pattern matching during the copy phase.

### 2. Copy source tree to staging

Walk the source tree with `find` (handling `-type f`, `-type l`, `-type d`).
For each entry:

- **Symlinks**: Use `readlink` to get the target, then `ln -s` in staging.
  Do NOT dereference or follow symlinks.
- **Directories**: `mkdir -p` in staging.
- **Regular files**: `cp` to staging (preserves content; permissions will be
  normalized separately).

Apply exclusion checks before copying. The exclusion function should check:
1. Pattern-based exclusions from the ignore file
2. Mode-based exclusions (e.g., files with mode 0600)

### 3. Normalize permissions

Apply to the staging directory tree:

- **Directories**: `chmod 0755` (or whatever the spec requires)
- **Files with execute bit or shebang**: `chmod 0755`
- **All other regular files**: `chmod 0644`

**Critical**: Check the **source** file's original permissions for the execute
bit, not the staging copy. Use `stat -c '%a'` on the source file and test
`$(( 8#$mode & 8#111 ))`. Then check the staging copy for a shebang:

```bash
head -c 2 -- "$staging_file" | grep -q '^#!'
```

### 4. Normalize line endings

For text files only, strip carriage returns: `sed -i 's/\r$//' "$file"`

**Binary detection**: Use the `tr -d '\0'` byte-count method:

```bash
orig=$(wc -c < "$file")
stripped=$(tr -d '\0' < "$file" | wc -c)
if [[ "$orig" == "$stripped" ]]; then
    # text file — safe to run sed
    sed -i 's/\r$//' "$file"
fi
```

**Why not `grep -P '\x00'`**: PCRE treats `\x00` as a string terminator in many
implementations and silently fails to detect actual null bytes. The `tr` method
is reliable and portable.

Empty files have `orig == stripped == 0`, so they are treated as text (sed on an
empty file is a no-op — this is correct).

### 5. Create deterministic archive

```bash
tar --sort=name \
    --format=gnu \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@$MTIME" \
    -cf - -C "$staging_dir" . | \
    zstd -19 --long --no-check --single-thread -o "$output"
```

Key flags and their purposes:

| Flag | Purpose |
|---|---|
| `--sort=name` | Deterministic entry ordering |
| `--format=gnu` | Consistent tar format (variant may use `posix`/`pax`) |
| `--owner=0 --group=0 --numeric-owner` | Fixed ownership regardless of host |
| `--mtime="@EPOCH"` | Fixed timestamp for all entries |
| `-C staging .` | Archive relative paths from staging root |

**Do NOT use `-h`** (dereference) — symlinks must be preserved as symlinks.

### 6. Compression

The compression command must be single-threaded and deterministic:

```bash
zstd -19 --long --no-check --single-thread -f -o "$output"
```

- `--single-thread`: Ensures deterministic output (multi-threaded zstd may
  produce different output due to frame splitting)
- `--long`: Enables long-distance matching for better compression
- `--no-check`: Removes the content checksum from the frame (removes a source
  of non-determinism in some implementations)
- `-19`: Compression level (may vary by task spec)
- `-f`: Force overwrite of existing output file (zstd refuses to overwrite
  without this flag, which causes silent failures on re-runs)

## Reference Implementation Template

Below is a complete, tested script template that implements the staging-directory
pattern. Adapt the variables and pattern-matching logic for your specific task:

```bash
#!/bin/bash
set -euo pipefail

# ── Configuration (adapt for your task) ────────────────────────────
SRC_DIR="/app/src"
OUTPUT="/app/release.tar.zst"
DISTIGNORE="$SRC_DIR/.distignore"
MTIME="${SOURCE_DATE_EPOCH:-946684800}"

# Create staging directory
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# ── Parse exclusion rules ──────────────────────────────────────────
declare -a DIR_PATTERNS=()
declare -a GLOB_PATTERNS=()
declare -a DOUBLESTAR_DIR_PATTERNS=()
declare -a DOUBLESTAR_GLOB_PATTERNS=()

while IFS= read -r pattern; do
    [[ -z "$pattern" || "$pattern" == \#* ]] && continue
    if [[ "$pattern" == */ ]]; then
        pat="${pattern%/}"
        if [[ "$pat" == \*\*/* ]]; then
            DOUBLESTAR_DIR_PATTERNS+=("${pat#\*\*/}")
        else
            DIR_PATTERNS+=("$pat")
        fi
    elif [[ "$pattern" == \*\*/* ]]; then
        # **/*.ext or **/name patterns (deep file globs)
        DOUBLESTAR_GLOB_PATTERNS+=("${pattern#\*\*/}")
    else
        GLOB_PATTERNS+=("$pattern")
    fi
done < "$DISTIGNORE"

# ── Exclusion check ────────────────────────────────────────────────
is_excluded() {
    local relpath="$1"
    local basename="${relpath##*/}"
    local dp comp gp

    # Root-level directory patterns
    if [[ ${#DIR_PATTERNS[@]} -gt 0 ]]; then
        for dp in "${DIR_PATTERNS[@]}"; do
            [[ "$relpath" == "$dp" || "$relpath" == "$dp"/* ]] && return 0
        done
    fi

    # **/NAME/ patterns — match directory component at any depth
    if [[ ${#DOUBLESTAR_DIR_PATTERNS[@]} -gt 0 ]]; then
        for comp in "${DOUBLESTAR_DIR_PATTERNS[@]}"; do
            [[ "/$relpath/" == *"/$comp/"* ]] && return 0
        done
    fi

    # **/*.ext patterns — match file glob at any depth
    if [[ ${#DOUBLESTAR_GLOB_PATTERNS[@]} -gt 0 ]]; then
        for gp in "${DOUBLESTAR_GLOB_PATTERNS[@]}"; do
            # shellcheck disable=SC2254
            case "$basename" in
                $gp) return 0 ;;
            esac
        done
    fi

    # File glob patterns — match against basename (root level)
    if [[ ${#GLOB_PATTERNS[@]} -gt 0 ]]; then
        for gp in "${GLOB_PATTERNS[@]}"; do
            # shellcheck disable=SC2254
            case "$basename" in
                $gp) return 0 ;;
            esac
        done
    fi

    # Exclude regular files with mode 0600 (adapt threshold as needed)
    local fullpath="$SRC_DIR/$relpath"
    if [[ -f "$fullpath" && ! -L "$fullpath" ]]; then
        local mode
        mode=$(stat -c '%a' "$fullpath")
        [[ "$mode" == "600" ]] && return 0
    fi

    return 1
}

# ── Copy source tree to staging (preserving symlinks) ──────────────
cd "$SRC_DIR"
find . -mindepth 1 \( -type f -o -type l -o -type d \) -print0 | while IFS= read -r -d '' entry; do
    relpath="${entry#./}"
    is_excluded "$relpath" && continue

    if [[ -L "$entry" ]]; then
        target=$(readlink "$entry")
        mkdir -p "$STAGING/$(dirname "$relpath")"
        ln -s "$target" "$STAGING/$relpath"
    elif [[ -d "$entry" ]]; then
        mkdir -p "$STAGING/$relpath"
    elif [[ -f "$entry" ]]; then
        mkdir -p "$STAGING/$(dirname "$relpath")"
        cp -- "$entry" "$STAGING/$relpath"
    fi
done

# ── Normalize permissions ──────────────────────────────────────────
# Directories: 0755 (adapt as needed)
find "$STAGING" -type d -exec chmod 0755 {} +

# Files: check SOURCE permissions for execute bit, then check shebang
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    relpath="${f#$STAGING/}"
    src_file="$SRC_DIR/$relpath"
    src_mode=$(stat -c '%a' "$src_file")

    # Check if source had any execute bit set
    has_exec=0
    if [[ $(( 8#$src_mode & 8#111 )) -ne 0 ]]; then
        has_exec=1
    fi

    # Check for shebang in the staging copy
    has_shebang=0
    if head -c 2 -- "$f" 2>/dev/null | grep -q '^#!'; then
        has_shebang=1
    fi

    if [[ $has_exec -eq 1 || $has_shebang -eq 1 ]]; then
        chmod 0755 "$f"  # adapt as needed
    else
        chmod 0644 "$f"  # adapt as needed
    fi
done

# ── Normalize line endings (CRLF → LF) for text files only ────────
find "$STAGING" -type f -print0 | while IFS= read -r -d '' f; do
    # Binary detection via null-byte count
    orig=$(wc -c < "$f")
    stripped=$(tr -d '\0' < "$f" | wc -c)
    if [[ "$orig" == "$stripped" ]]; then
        # Text file — strip carriage returns (adapt direction as needed)
        sed -i 's/\r$//' "$f"
    fi
done

# ── Create deterministic tar + zstd archive ────────────────────────
tar --sort=name \
    --format=gnu \
    --owner=0 --group=0 --numeric-owner \
    --mtime="@$MTIME" \
    -cf - -C "$STAGING" . | \
    zstd -19 --long --no-check --single-thread -f -o "$OUTPUT"
```

**Key implementation notes:**
- The template handles all four pattern categories from .distignore (root dirs, nested root dirs, deep dirs, deep file globs, and root file globs)
- Symlinks are preserved via `readlink` + `ln -s` (never dereferenced)
- Permission checks use the source file's mode, not the staging copy
- Binary detection uses `tr -d '\0'` byte-count (not `grep -P '\x00'`)
- The `-f` flag on zstd prevents silent failures on re-runs
- All `find` operations use `-print0` and `read -d ''` for safe filename handling

## Variation Points (from spec axes)

### source_tree_content_and_exclusions

- **What changes**: Directory names, file extensions, ignore-file format,
  symlink targets, scale of nesting, special characters in filenames.
- **What stays invariant**: The exclusion-matching architecture (parse patterns
  → classify → match during copy). The four pattern categories (root dir,
  deep dir, deep file glob, root file glob) cover gitignore-style syntax.
- **Edge cases**: Files with spaces, `$`, `!` in names — use null-delimited
  `find -print0` and `read -d ''` throughout.

### normalization_rules

- **What changes**: Permission mapping rules, timestamp source, text-file
  detection heuristic, line-ending target (LF vs CRLF), owner/group policy.
- **What stays invariant**: The staging-directory approach; per-file decision
  logic; binary detection via null-byte counting.
- **Adaptation**: The permission rules and line-ending direction are
  configurable. The script should read these from the task specification, not
  hardcode them.

### archive_format_and_compression

- **What changes**: Tar format (`gnu`, `posix`, `pax`), compression algorithm
  and level, output path, environment variable names, verification hashes.
- **What stays invariant**: The need for `--sort`, fixed owner/group, fixed
  mtime, single-threaded compression, and relative path archiving from staging.
- **Adaptation**: The exact tar flags and compression command are parameterized
  by the task specification.

## Reproducibility Verification

To confirm bit-for-bit reproducibility:

```bash
hash1=$(sha256sum "$output" | cut -d' ' -f1)
# Re-run the build
hash2=$(sha256sum "$output" | cut -d' ' -f1)
[[ "$hash1" == "$hash2" ]]  # must be true
```

If hashes differ, common causes:
1. Non-deterministic file ordering (missing `--sort=name`)
2. Host-dependent timestamps (missing `--mtime`)
3. Host-dependent ownership (missing `--owner=0 --group=0 --numeric-owner`)
4. Multi-threaded compression producing different frame layouts
5. Residual filesystem metadata leaking into the archive

## Common Pitfalls

1. **`grep -P '\x00'` for binary detection**: Unreliable — PCRE treats null as
   string terminator. Use `tr -d '\0'` byte comparison instead.
2. **Checking `-x` on staging files after copy**: When running as root, `cp`
   preserves source permissions, but it's safer to check the source file's mode
   directly with `stat`.
3. **Empty arrays with `set -u`**: In bash < 4.4, `"${empty_array[@]}"` in a
   `for` loop causes "unbound variable". Guard with `${#arr[@]} -gt 0` check.
4. **`find | while` subshell**: Variables set inside the loop are lost. This is
   fine when the loop only performs file operations.
5. **Following symlinks during copy**: Always use `readlink` + `ln -s`, never
   `cp -L` or tar `-h`.
6. **tar `--exclude` for gitignore patterns**: tar's fnmatch `*` does not cross
   `/`, so `--exclude='**/__pycache__'` does not work. Handle exclusions during
   the copy phase instead.
7. **zstd refusing to overwrite**: zstd will not overwrite an existing output
   file without `-f` flag. This causes silent failures on re-runs — the old
   archive persists and the new tar output is discarded. Always use `-f -o`.
