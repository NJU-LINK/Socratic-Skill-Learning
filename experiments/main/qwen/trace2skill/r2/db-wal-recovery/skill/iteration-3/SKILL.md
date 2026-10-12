---
name: db-wal-recovery
description: General starting point for solving tasks in the db-wal-recovery family.
---

# db-wal-recovery

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.



## Critical Recovery Protocol

1. **Backup Artifacts Immediately**: Before running ANY commands or opening the database, create backups of the database and WAL files. SQLite will silently delete or truncate a WAL file if its header magic bytes are unrecognized (e.g., XOR-obfuscated or corrupted).
   ```bash
   cp main.db main.db.bak && cp main.db-wal main.db-wal.bak
   ```
2. **Byte-Level Inspection Before SQLite**: **DO NOT** run `sqlite3` or open the database before inspecting the WAL file. Use `xxd` or `hexdump` to analyze WAL bytes, headers, and frames to identify reversible corruption (e.g., XOR, base64, byte-swapped). When capturing the full file for repair, do not truncate the output (e.g., avoid `| head`).
3. **Avoid Destructive Pragmas**: NEVER run `PRAGMA wal_checkpoint`, `PRAGMA journal_mode`, or any write queries until the WAL is repaired at the byte level.
4. **Handle All DML Operations**: WAL frames contain full page images that can encode arbitrary DML (INSERT, UPDATE, DELETE). Do not assume the WAL only appends new trailing rows or that base database values are final. Parse page images to identify new, modified, and deleted cells compared to the base database.
5. **Extract, Do Not Guess**: Parse actual data from the repaired WAL. Never fabricate or extrapolate data based on patterns in the base database.
6. **Repair Then Open**: Diagnose corruption, repair the WAL at the byte level, and only then use `sqlite3` to recover the data.
