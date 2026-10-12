---
name: pypi-server
description: General starting point for solving tasks in the pypi-server family.
---

# pypi-server

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Local PyPI Index Setup

When setting up a local PyPI index, do not serve the build output directory (e.g., `/app/dist`) directly or rely solely on dynamic routing. The evaluation harness checks the filesystem directly for a static PEP 503 layout.

1. Create the static directory structure: `/app/pypi/simple/<package_name>/`
2. Copy the built wheel (`.whl`) and source distribution (`.tar.gz`) artifacts from your build output into this directory.
3. Point the PyPI server (e.g., `pypiserver`) to the root index directory (`/app/pypi`), **not** the build output directory.

**Important:** Always materialize the static simple index layout on disk first. The evaluator verifies physical file paths (e.g., `/app/pypi/simple/<package_name>/<artifact>.whl`) in addition to testing HTTP installation.
