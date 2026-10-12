---
name: db-wal-recovery
description: Reusable instructions for db-wal-recovery tasks.
---

# db-wal-recovery

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Back up WAL before database access
content: When a task involves a database with an auxiliary write-ahead log or journal file, copy the auxiliary file to a safe location before opening the database with any query tool, then analyze the backup to diagnose any encoding or corruption before attempting repair.
