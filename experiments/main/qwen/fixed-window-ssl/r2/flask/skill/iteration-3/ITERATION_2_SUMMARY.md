# Iteration 2: SQLite Path Resolution Fix

## Problem Identified from Iteration 1

**Test Failures:** 3 out of 9 tests failed with `sqlite3.OperationalError: no such table: accounts`

The failing tests were:
- `test_setup_idempotent`
- `test_transfer_with_description`
- `test_balances_updated_correctly`

All three tests opened **separate database connections** using relative paths like `sqlite3.connect("bank.db")` to verify the data.

## Root Cause

The original implementation used:
```python
DB_PATH = os.path.join(os.getcwd(), 'bank.db')
```

This captures the **current working directory at import time** (when the module is first loaded). However:

1. The test harness may change CWD between module import and test execution
2. Tests open separate connections using relative paths: `sqlite3.connect("bank.db")`
3. These relative paths resolve against CWD **at connection time**, not import time
4. Result: App writes to `/path/A/bank.db`, tests read from `/path/B/bank.db` → "no such table"

## Solution

Use a **relative path string** that resolves at each `connect()` call:

```python
# WRONG — captures CWD at import time
DB_PATH = os.path.join(os.getcwd(), 'bank.db')

# CORRECT — resolved at each connect() call
DB_PATH = 'bank.db'
```

## Why This Works

- `sqlite3.connect('bank.db')` resolves the relative path against CWD **when called**
- Both the app's connection and test's connection use the same resolution mechanism
- They always point to the same file, regardless of when CWD changes

## Skill Updates

Added to `skill/flask/SKILL.md`:

1. **Database Path Resolution** section in SQLite3 persistence model
2. **Common Pitfalls** entry #11 documenting this trap

## Verification

All 10 tests now pass, including the 3 that previously failed:
- ✅ `test_setup_idempotent` - External connection sees tables
- ✅ `test_transfer_with_description` - External connection sees transaction records
- ✅ `test_balances_updated_correctly` - External connection sees updated balances

## Key Lesson

**Family Invariant:** Every SQLite3 case in this family will specify "database in the current working directory". The correct implementation is always a relative path string, never an absolute path constructed at import time.

This is a **critical trap** because:
- It only manifests when tests open separate connections
- It's timing-dependent (depends on when CWD changes)
- The error message ("no such table") doesn't obviously point to path resolution
- It passes in simple cases where app and tests use the same connection
