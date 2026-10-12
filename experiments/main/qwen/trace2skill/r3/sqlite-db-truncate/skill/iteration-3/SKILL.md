---
name: sqlite-db-truncate
description: General starting point for solving tasks in the sqlite-db-truncate family.
---

# sqlite-db-truncate

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Handling Corrupted Databases

If `sqlite3` reports "database disk image is malformed" or you encounter truncated/corrupted data, standard tools will fail. Read [references/sqlite-corruption-recovery.md](references/sqlite-corruption-recovery.md) for procedures on extracting schemas, parsing raw SQLite pages, identifying bit-flip corruptions, and reconstructing zeroed cells from surviving byte fragments.