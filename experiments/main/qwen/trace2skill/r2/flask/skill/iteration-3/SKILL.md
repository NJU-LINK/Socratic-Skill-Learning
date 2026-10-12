---
name: flask
description: General starting point for solving tasks in the flask family.
---

# flask

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Common Pitfalls

- **SQLite Database Paths**: When a task requires a SQLite database in the current working directory, pass the relative filename directly to `sqlite3.connect('app.db')` inside the request-scoped connection function. **Do not** use `os.getcwd()` at the module level to construct an absolute path (e.g., `DB_PATH = os.path.join(os.getcwd(), 'app.db')`). Test frameworks may change the working directory after import, causing the app and tests to operate on different files if the path is resolved at import time.