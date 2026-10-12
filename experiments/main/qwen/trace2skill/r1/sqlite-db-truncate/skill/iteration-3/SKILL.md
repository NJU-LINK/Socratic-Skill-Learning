---
name: sqlite-db-truncate
description: General starting point for solving tasks in the sqlite-db-truncate family.
---

# sqlite-db-truncate

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Handling Corrupted or Truncated Databases
If `sqlite3` fails to open the database or reports 'database disk image is malformed', fall back to manual binary parsing.
- Recover the schema from page 1's `sqlite_master` record.
- Parse raw B-tree leaf pages to extract records and validate serial types against payload lengths.
- Correct bit-flipped serial type codes or bypass strict header parsing using pattern matching.
- Cross-reference recovered data with a fresh database to identify all corruption points.
See [references/corrupted-sqlite-recovery.md](references/corrupted-sqlite-recovery.md) for detailed binary parsing structures, python snippets, and correction patterns.

