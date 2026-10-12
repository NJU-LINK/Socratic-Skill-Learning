---
name: db-wal-recovery
description: Reusable instructions for db-wal-recovery tasks.
---

# db-wal-recovery

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Back up WAL before database access
content: When the task involves a corrupted or encoded write-ahead log file alongside a base database, copy or dump the raw log file bytes before opening the database with any database tool, because the tool may auto-checkpoint and permanently delete the log on first open.
