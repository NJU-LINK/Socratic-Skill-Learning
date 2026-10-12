---
name: pypi-server
description: Reusable instructions for pypi-server tasks.
---

# pypi-server

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Static PEP 503 index under pypi directory
content: When setting up a local package index to serve built artifacts, create a pypi directory under the project workspace as the index root with artifacts placed physically at root/simple/package/, and configure the server to serve from that layout so that both HTTP requests and on-disk file existence checks at root/simple/package/ succeed.
