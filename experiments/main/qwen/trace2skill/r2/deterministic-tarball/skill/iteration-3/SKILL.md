---
name: deterministic-tarball
description: General starting point for solving tasks in the deterministic-tarball family.
---

# deterministic-tarball

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Build Script Requirements

- **Use Exact CLI Commands**: When the task specifies exact CLI tools and flags (e.g., `tar --format=gnu`, `zstd -19 --long --no-check --single-thread`), invoke them directly in a shell script (e.g., `build.sh`). Always write out required flags explicitly (e.g., `--sort=name`, `--owner=0`, `--group=0`, `--mtime=...`) to pass static string-matching assertions.
- **Avoid Language Libraries for Archiving/Compression**: Do not use language-native libraries (like Python's `tarfile` or `zstd` bindings) to perform the archiving or compression. Evaluation suites often include static string-matching tests (e.g., `assert "--format=gnu" in script`) that will fail if libraries are used instead of the exact CLI commands.
- **Hybrid Approach**: If a scripting language like Python is needed for complex logic (e.g., parsing `.distignore`, normalizing line endings), use it to stage files to disk, then shell out to the exact `tar` and `zstd` CLI commands required by the prompt.

## Core Workflow for Deterministic Archives
1. **Staging Directory**: Use a temporary staging directory (`mktemp -d`; `chmod 0755`) to separate exclusion filtering, permission normalization, and line-ending conversion from the final tar step.
2. **Normalization**: Use an embedded Python script to parse `.distignore` (gitignore-style), detect binaries (check first 8KB for `\x00`), convert CRLF→LF for text files, and set permissions (0755 for shebangs/executables, 0644 otherwise). See [references/normalization-patterns.md](references/normalization-patterns.md) for implementation details.
3. **Deterministic Tar**: Export `LC_ALL=C`. Run GNU tar: `--sort=name --mtime=@EPOCH --owner=0 --group=0 --numeric-owner --format=gnu -C staging -cf - .`
4. **Compression**: Pipe to compressor with `--force` to allow overwrites (e.g., `zstd -19 --long --no-check --single-thread --force -o "$OUT"`).
