---
name: pypi-server
description: General starting point for solving tasks in the pypi-server family.
---

# pypi-server

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## PEP 503 On-Disk Layout

When setting up a local PyPI index, verifiers often assert the physical PEP 503 filesystem layout in addition to HTTP accessibility.

- **Do not** serve a flat build output directory (e.g., `dist/`) directly, as this will fail filesystem existence checks.
- **Do not** rely solely on `pypiserver`'s dynamic URL routing, as it maps `/simple/<pkg>/` to `<root>/<pkg>/` on disk without actually creating a `simple/` directory.
- Manually create the exact expected directory tree (e.g., `mkdir -p /app/pypi/simple/<package_name>/`).
- Copy the built artifacts (wheel and sdist) into the package directory.
- Serve the index root directory (e.g., `/app/pypi`) using `pypi-server` or a static HTTP server, ensuring the physical on-disk paths match the expected layout.