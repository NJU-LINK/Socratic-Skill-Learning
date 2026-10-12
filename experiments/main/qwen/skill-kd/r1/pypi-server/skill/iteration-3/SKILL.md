---
name: pypi-server
description: Reusable instructions for pypi-server tasks.
---

# pypi-server

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Static PEP 503 index layout
content: When a task requires hosting built artifacts via a local package index, create a static PEP 503 directory tree with artifact files physically copied into simple per-package subdirectories under a pypi root directory in the project workspace, then serve that tree with a basic HTTP server on the required port.
