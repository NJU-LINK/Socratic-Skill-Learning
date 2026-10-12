---
name: flask
description: Reusable instructions for flask tasks.
---

# flask

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Relative database paths for test clients
content: When implementing a web application with file-based persistence that will be tested through an in-process test client, use a plain relative filename for the database path so it resolves at each connection call rather than computing an absolute path at module import time.
