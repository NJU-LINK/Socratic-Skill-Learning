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
non-empty, non-comment line into one of three categories:

| Pattern form | Meaning | Matching strategy |
|---|---|---|
| `name/` | Root-level directory | `relpath == "name"` or `relpath starts with "name/"` |
| `**/name/` | Directory at any depth | Check if `"/$relpath/"` contains `"/name/"` |
| `*.ext` | File glob | Match against basename using shell `case` glob |

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

## Variation Points (from spec axes)

### source_tree_content_and_exclusions

- **What changes**: Directory names, file extensions, ignore-file format,
  symlink targets, scale of nesting, special characters in filenames.
- **What stays invariant**: The exclusion-matching architecture (parse patterns
  → classify → match during copy). The three pattern categories (root dir,
  deep dir, file glob) cover gitignore-style syntax.
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
