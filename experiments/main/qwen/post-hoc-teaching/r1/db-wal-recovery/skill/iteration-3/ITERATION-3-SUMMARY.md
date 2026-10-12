# Iteration 3 Summary

## Root Cause Analysis

After reviewing the iteration 2 failure trajectory, I identified the actual root cause:

**The solver ran `sqlite3 main.db` before backing up the WAL file.**

When sqlite3 opens a database with a WAL file, it automatically checkpoints the WAL, which:
1. Applies the WAL changes to the main database
2. **Deletes the WAL file**

This happened at tool call 107 in the trajectory:
```bash
sqlite3 main.db ".schema" && sqlite3 main.db "SELECT * FROM items;"
```

After this command, `main.db-wal` no longer existed. The solver then spent 60+ tool calls trying to recover the deleted WAL file using increasingly desperate techniques (debugfs, block device access, bind mount escape, etc.), all blocked by container security. Eventually the solver gave up and guessed the data, producing incorrect values.

## Changes Made

### 1. Added Phase 0: Preserve the WAL File (CRITICAL)

Inserted a new Phase 0 **before** Phase 1 in the Recovery Pipeline:

```markdown
### Phase 0: Preserve the WAL File (CRITICAL — DO THIS FIRST)

**⚠️ NEVER run sqlite3 on the database before completing this step.**

Opening a database with sqlite3 may cause SQLite to auto-checkpoint, consuming
or deleting the WAL file. If the WAL is deleted before you can read it,
recovery is impossible.

1. Read the entire WAL file into memory: `wal_data = open('<db>-wal', 'rb').read()`
2. Write a backup copy: `open('<db>-wal.backup', 'wb').write(wal_data)`
3. ONLY THEN proceed to Phase 1

All subsequent work uses the in-memory `wal_data` copy, not the on-disk file.
```

### 2. Updated Diagnostic Checklist

Moved WAL backup to item #1 with warning symbol:

```markdown
- [ ] **⚠️ BACKUP the WAL file into memory and to disk BEFORE any sqlite3 interaction**
- [ ] Identify all files: `.db`, `.db-wal`, `.db-shm`, any additional WAL files
- [ ] Check if base DB exists and is readable; count records it contains (WITHOUT opening sqlite3 — use raw file reads or check the backup)
```

### 3. Strengthened Common Pitfalls #1

Made the auto-checkpoint warning the first and most prominent pitfall:

```markdown
1. **🚨 SQLite auto-checkpoint destroys the WAL (MOST COMMON FAILURE)**: Opening a 
   database with `sqlite3` will auto-checkpoint the WAL, consuming or deleting it.
   This is IRREVERSIBLE — once the WAL is gone, the data it contains is lost.
   **You MUST read and backup the WAL file into memory before running ANY sqlite3
   command.** This is Phase 0 of the recovery pipeline. Never run `sqlite3 main.db`
   until you have completed Phase 0 and are ready to apply the decoded WAL.
```

### 4. Updated Example Code

Made the example more explicit about Phase 0:

```python
# ⚠️ PHASE 0: Read the WAL file BEFORE any sqlite3 interaction
# This is CRITICAL — running sqlite3 before this step will destroy the WAL
wal_data = open(wal_path, 'rb').read()
print(f"WAL file backed up: {len(wal_data)} bytes")

# Now it's safe to use sqlite3 if needed
```

### 5. Kept UPDATE Documentation

The UPDATE operation documentation from the previous iteration is still valuable for a different failure mode (where the WAL is successfully recovered but the solver only looks at new records and ignores modified ones). This is kept as pitfall #6.

## Expected Impact

These changes should prevent the iteration 2 failure by:

1. **Making Phase 0 impossible to miss**: It's now the first instruction in the Recovery Pipeline, with clear warning symbols
2. **Emphasizing the consequence**: The documentation explicitly states that running sqlite3 before Phase 0 is IRREVERSIBLE
3. **Providing a clear sequence**: Phase 0 → Phase 1 → ... makes it clear that WAL preservation comes first
4. **Updating the checklist**: The diagnostic checklist now has WAL backup as item #1
5. **Strengthening the pitfall**: The most common failure is now the first pitfall with the strongest warning

## Test Coverage

The skill should now handle:
- ✅ WAL preservation before any sqlite3 interaction (Phase 0)
- ✅ Encoding detection (XOR, base64, NOT, byte-swap, etc.)
- ✅ Checksum validation and repair
- ✅ Transaction grouping and atomic application
- ✅ Salt validation for multi-session WALs
- ✅ UPDATE operations (not just INSERTs)
- ✅ B-tree page parsing for Strategy C
- ✅ Verification of both new and updated records
