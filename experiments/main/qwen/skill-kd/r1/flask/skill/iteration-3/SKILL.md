---
name: flask
description: Reusable instructions for flask tasks.
---

# flask

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Flask SQLite relative path
content: When a Flask app uses file-based persistence and will be imported and tested via the test client, resolve the database path at connection time using a simple relative filename rather than capturing the working directory at module import time.
