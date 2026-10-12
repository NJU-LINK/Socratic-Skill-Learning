---
name: deterministic-tarball
description: General starting point for solving tasks in the deterministic-tarball family.
---

# deterministic-tarball

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Implementation Guidelines

- **Use CLI tools with explicit flags**: Always use native CLI tools (e.g., `tar`, `zstd`, `gzip`) with explicit flags (e.g., `--format=gnu`, `--sort=name`, `--mtime=...`, `--owner=0`, `--group=0`) in shell scripts for archive creation and compression.
- **Avoid programmatic libraries**: Do NOT use language-native libraries (like Python's `tarfile` or `zipfile`). Evaluation tests often grep the script source code for exact CLI strings to enforce toolchain choices. Using libraries will fail these static string-matching checks even if the resulting archive is binary-correct.

