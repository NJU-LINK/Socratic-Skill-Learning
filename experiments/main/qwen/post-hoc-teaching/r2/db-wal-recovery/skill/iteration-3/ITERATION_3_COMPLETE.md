# Iteration 3 Complete: db-wal-recovery Skill

## Issue Identified from Iteration 2

**Score**: 4/7 tests passed (57%) - REGRESSION from iteration 1 (7/7)

**Root Cause**: Agent opened database with sqlite3 BEFORE decoding the WAL file
- SQLite saw invalid (XOR-encoded) WAL and DELETED it
- Agent left with only base database (5 records)
- Expected: 11 records with updates (e.g., id=1, value=150)
- Got: 5 records without updates (e.g., id=1, value=100)

**Why it happened**: Warning "Never open database with sqlite3 before decoding WAL" was buried in "Important Pitfalls" section at bottom of SKILL.md

## Fixes Applied in Iteration 3

### 1. Added Critical Warning at Document Top
```markdown
## ⚠️ CRITICAL WARNING ⚠️

**NEVER open the database with sqlite3 BEFORE decoding the WAL file!**

SQLite automatically deletes invalid WAL files when you open a database...
```

### 2. Updated Quick Start Section
```markdown
**STEP 1: Copy and run the recovery script IMMEDIATELY (before doing anything else):**

**DO NOT** explore the database with sqlite3 before running the script...
```

### 3. Enhanced SQLite WAL Behavior Section
```markdown
- **⚠️ SQLite deletes invalid WAL files on open** — this is the #1 cause of data loss
  - NEVER run `sqlite3 database.db` or `sqlite3.connect('database.db')` before decoding the WAL
  - Even a simple `SELECT` query will trigger WAL deletion if the WAL appears invalid
  - Always decode the WAL file FIRST, then write it back, THEN open the database
```

### 4. Added Warning to Recovery Procedure
```markdown
### ⚠️ BEFORE YOU START: Critical Order of Operations

**You MUST follow this exact order:**
1. **DECODE the WAL file** (XOR, base64, etc.) — do this FIRST
2. **WRITE the decoded WAL** back to disk alongside the database
3. **THEN** you can open the database with sqlite3

**NEVER** open the database with sqlite3 before step 2 is complete...
```

### 5. Enhanced Important Pitfalls Section
```markdown
1. **⚠️ NEVER open database with sqlite3 before decoding WAL** ⚠️
   - SQLite deletes invalid WAL files on open
   - Even `SELECT * FROM table` will trigger deletion
   - This is the #1 cause of recovery failure
   - Always decode WAL FIRST, write it back, THEN open database
```

## Result

Warning now appears in **5 locations** throughout SKILL.md:
1. Top of document (critical warning box)
2. Quick Start section
3. SQLite WAL Behavior section
4. Recovery Procedure section
5. Important Pitfalls section

This makes it **impossible to miss** this critical rule, even if agent only skims documentation.

## Package Status

Active files (26.5 KB):
- **SKILL.md** (9.5 KB) - Enhanced with prominent warnings in 5 locations
- **wal_recovery.py** (17 KB) - Unchanged (already robust)

The skill is now much more robust against the most common cause of failure.

## Key Insight

The iteration 2 failure was not due to a bug in the recovery script or missing functionality. It was due to the agent violating a critical operational rule that was not prominent enough in the documentation. By making the warning impossible to miss, we prevent this class of failure entirely.

This demonstrates that **documentation placement and emphasis** are as important as technical correctness when designing skills for autonomous agents.
