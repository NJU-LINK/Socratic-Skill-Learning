---
name: pypi-server
description: General starting point for solving tasks in the pypi-server family.
---

# pypi-server

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Package Index Filesystem Layout

When setting up a local PyPI-compatible index, explicitly construct the PEP 503 `simple/` directory hierarchy on disk. Do not rely solely on dynamic servers like `pypiserver` serving from a flat build directory (e.g., `/app/dist/`), as evaluation tests may assert the physical filesystem path matches the simple index URL structure.

1. Create the directory structure: `/app/pypi/simple/<package_name>/`
2. Copy the built artifacts (wheel and sdist) into this directory.
3. Serve the `/app/pypi` root directory to satisfy both HTTP requests and filesystem existence checks.
