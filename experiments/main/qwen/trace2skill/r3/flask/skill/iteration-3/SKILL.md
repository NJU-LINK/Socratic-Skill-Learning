---
name: flask
description: General starting point for solving tasks in the flask family.
---

# flask

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Common Pitfalls

- **Database/File Paths**: When a task requires a database or file in the current working directory, use a relative path string (e.g., `'bank.db'`) directly in `sqlite3.connect()` or `open()` inside your connection function or request handler. **DO NOT** evaluate `os.getcwd()` or `os.path.join(os.getcwd(), ...)` at the module level. Module-level evaluation freezes the absolute path at import time, which causes "no such table" or "missing file" errors if the test harness changes directories between import and execution.