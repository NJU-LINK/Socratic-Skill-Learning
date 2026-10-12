---
name: db-wal-recovery
description: General starting point for solving tasks in the db-wal-recovery family.
---

# db-wal-recovery

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Critical WAL Recovery Procedure

**WARNING: Never open the database with `sqlite3` or any SQLite library before backing up and repairing the WAL.** 
Native tools will silently checkpoint, auto-repair, or truncate an invalid/encrypted WAL file upon connection, permanently destroying hidden data.

### 1. Artifact Preservation
- **Backup everything**: Copy all database files (`.db`, `.db-wal`, `.db-shm`) to `.bak` files or a safe directory.
- **Fully dump binary artifacts**: Capture the *entire* content of the WAL file using `xxd <wal_file> > wal.hex`. Do not rely on partial dumps, as record data often resides at the end of pages.

### 2. Diagnosis & Repair
- **Diagnose**: Inspect the WAL file using raw byte operations to identify encoding, encryption, or corruption (e.g., invalid magic numbers).
- **Decrypt/Repair**: Write the corrected/decrypted bytes back to the WAL file using raw byte operations.
- **Verify Header**: Ensure the WAL header is valid before proceeding.

### 3. WAL Analysis Guidelines
- **Not just inserts**: WAL frames contain full page images and may include **updates and deletes** to existing records. Guessing contents from base data patterns will fail.
- **Parse cell content**: Parse the WAL frame page data to extract actual cell content rather than assuming a simple append pattern.

### 4. Safe Reading
- **Read**: ONLY AFTER the WAL is verified valid and fully analyzed, open the database with `sqlite3` to read the merged data.