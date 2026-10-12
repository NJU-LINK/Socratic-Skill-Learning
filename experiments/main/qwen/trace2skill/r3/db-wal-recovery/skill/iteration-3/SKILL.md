---
name: db-wal-recovery
description: General starting point for solving tasks in the db-wal-recovery family.
---

# db-wal-recovery

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Critical WAL Recovery Workflow

**CRITICAL: Never open the database with `sqlite3` CLI or Python's `sqlite3` module before fixing the WAL.** SQLite validates the WAL header on open and will automatically checkpoint or delete the WAL file if it appears invalid, encrypted, or corrupted. In containerized environments, deleted files are typically unrecoverable, permanently destroying the forensic evidence you need.

1. **Preserve Artifacts (Step Zero)**: IMMEDIATELY backup the `.db` and `.db-wal` files using raw file operations (e.g., `cp`, Python `shutil.copy`) before running any tool that might open the database. Apply all subsequent fixes to the backup, not the original.
   ```bash
   cp main.db main.db.backup
   cp main.db-wal main.db-wal.backup
   ```
2. **Raw Analysis & Repair**: Inspect the WAL backup using hex dumps (`xxd`) and Python byte manipulation. If encrypted or obfuscated, deduce the transformation (e.g., single-byte XOR by comparing the corrupted header against SQLite WAL magic numbers `0x377f0682` or `0x377f0683`) and repair the backup file.
3. **Account for All Operations**: WAL files contain full page images, which include **updates**, **deletes**, and schema changes, not just new inserts. Never assume the WAL only adds new records.
4. **Extract, Don't Guess**: Do not guess missing data patterns. Parse the decrypted WAL manually or fix its header before allowing SQLite to read it, and extract the exact data from the decrypted WAL contents.
5. **Recover and Verify**: Only use SQLite tools to read the database *after* the WAL is fully repaired and valid. Use the repaired WAL with `sqlite3` to apply all changes to the base database state, then verify the final result.