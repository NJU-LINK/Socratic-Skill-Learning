---
name: db-wal-recovery
description: Reusable instructions for db-wal-recovery tasks.
---

# db-wal-recovery

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Backup journal before database access
content: When a task involves a corrupted or encoded database journal file, copy the journal to a safe location before opening the database with any query tool, then decode or repair the journal bytes directly to extract the actual changes it contains rather than inferring missing values from patterns in the base data.
