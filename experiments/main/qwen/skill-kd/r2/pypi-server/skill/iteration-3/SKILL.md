---
name: pypi-server
description: Reusable instructions for pypi-server tasks.
---

# pypi-server

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Static PEP 503 index layout
content: When setting up a local package index, create a pypi directory under the project root containing a PEP 503 simple directory tree with built artifacts physically placed in per-package subdirectories, and configure the index server to serve from that tree rather than generating the index dynamically from a flat package directory.
