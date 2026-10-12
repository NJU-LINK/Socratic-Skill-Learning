---
name: flask
description: General starting point for solving tasks in the flask family.
---

# flask

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

## Common Pitfalls

- **Database/File Paths**: When a task requires a file (like a SQLite database) in the current working directory, pass the relative filename directly to the library (e.g., `sqlite3.connect('bank.db')`). **DO NOT** cache `os.getcwd()` in global constants (e.g., `os.path.join(os.getcwd(), 'bank.db')`) at the module level. The test environment may change the working directory between import and execution, causing path mismatches and 'no such table' errors. Resolve paths dynamically inside request handlers or rely on native relative path resolution.


## Database and State Management

- **Idempotent Seeding**: Use `CREATE TABLE IF NOT EXISTS` and check for existing records before `INSERT` to prevent duplication on repeated setup calls.
- **Pre-Transaction Validation**: Validate all request constraints and return HTTP errors *before* opening DB connections or starting transactions.
- **Explicit Transactions**: For atomic multi-step mutations (e.g., transfers), use explicit `BEGIN`, `COMMIT`, and `ROLLBACK` rather than autocommit. Roll back on validation failures or exceptions.
