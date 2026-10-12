# Implementation Patterns

## Table of Contents
- [Python Staging and Normalization](#python-staging-and-normalization)
- [Robust .distignore Pattern Matching](#robust-distignore-pattern-matching)
- [Deterministic Tar and Zstd Pipeline](#deterministic-tar-and-zstd-pipeline)

## Python Staging and Normalization
When building deterministic archives with complex exclusion rules, text/binary detection, and line-ending normalization, use an embedded Python script to copy files into a temporary staging directory.
- Use `os.walk` with manual pruning of `dirnames` based on parsed `.distignore` patterns.
- Detect binary files by checking for null bytes (`b'\x00' in data`).
- Read text files in binary mode, normalize CRLF to LF, and write back.
- Preserve symlinks using `os.readlink`/`os.symlink` without following them.
- Explicitly exclude files with `stat.S_IMODE(mode) == 0o600`.
- Normalize permissions (0755 for dirs/shebangs, 0644 otherwise).
- Set mtimes in the staging area before archiving.

## Robust .distignore Pattern Matching
Implement a custom pattern matcher that checks against path components rather than just the full path string:
- **Directory patterns (trailing `/`)**: Strip the slash and check if the relative path equals it or starts with it followed by a separator.
- **Recursive globs (`**/`)**: Extract the inner pattern and check if any individual path component matches it using `fnmatch`.
- **Standard file globs (no `/`)**: Match strictly against the file's basename.
This prevents over-matching and correctly handles nested directory exclusions like `**/__pycache__/`.

## Deterministic Tar and Zstd Pipeline
To achieve bit-for-bit reproducibility, use specific GNU tar and zstd flags that eliminate non-determinism from metadata, ordering, and compression.

```bash
rm -f "$OUTPUT"
tar --sort=name --format=gnu --owner=0 --group=0 --numeric-owner --mtime="@${SOURCE_DATE_EPOCH}" -C "$STAGING" -cf - . | zstd -19 --long --no-check --single-thread -o "$OUTPUT"
```

- `rm -f "$OUTPUT"`: **Critical**. `zstd` will abort with an error if the output file already exists when reading from stdin, breaking idempotency.
- `--sort=name`: ensures deterministic entry order.
- `--format=gnu`: handles long paths correctly.
- `--owner=0 --group=0 --numeric-owner`: eliminates user/group metadata non-determinism.
- `--mtime="@${SOURCE_DATE_EPOCH}"`: reliably overrides filesystem timestamps for all entries including symlinks.
- `zstd -19 --long --no-check --single-thread`: `--no-check` and `--single-thread` prevent checksum and multi-threading non-determinism.