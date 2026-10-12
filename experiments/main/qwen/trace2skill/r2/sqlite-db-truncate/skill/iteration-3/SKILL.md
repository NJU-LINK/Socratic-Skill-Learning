---
name: sqlite-db-truncate
description: General starting point for solving tasks in the sqlite-db-truncate family.
---

# sqlite-db-truncate

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Database Corruption and Truncation
If `sqlite3` rejects a database as malformed or truncated, standard queries will fail. Refer to [references/sqlite-binary-recovery.md](references/sqlite-binary-recovery.md) for manual binary parsing, schema recovery from page 1, single-bit-flip corruption detection, and free-space sanitization.

