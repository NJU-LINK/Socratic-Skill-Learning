---
name: deterministic-tarball
description: General starting point for solving tasks in the deterministic-tarball family.
---

# deterministic-tarball

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

## Core Workflow
1. **Inspect Inputs**: Identify the source tree and any exclusion rules (e.g., `.distignore`).
2. **Normalize & Stage**: Use an embedded Python script to walk the source tree, apply exclusion rules, normalize line endings (CRLF to LF for text files), preserve symlinks, and prepare a staging directory. Pure bash is fragile for recursive globs and binary detection.
3. **Archive**: Use GNU tar CLI with strict deterministic flags piped to zstd CLI. Always `rm -f "$OUTPUT"` before archiving to prevent zstd overwrite failures on subsequent runs.
4. **Verify**: Check the archive contents and reproducibility before finishing.

## Implementation Guidelines
- **Use CLI tools for archiving and compression**: When the task specifies command-line flags (e.g., `--format=gnu`, `zstd -19`), use the actual CLI tools (`tar`, `zstd`) in your `build.sh` script rather than programmatic libraries (like Python's `tarfile`). Tests often perform literal substring matching on the script source to verify these flags.
- **Hybrid approach**: Use Python for complex file preprocessing (e.g., `.distignore` matching, permission normalization), but pipe or pass the results to the `tar` CLI for the final archive creation to ensure all required flags are visible in the script text.

## References
- [references/implementation-patterns.md](references/implementation-patterns.md): Proven Python staging techniques, `.distignore` matching logic, and exact GNU tar/zstd flags for bit-for-bit reproducible archives.
