# Iteration 2 Completion Summary

## Objective
Address the most consequential weakness from iteration 1 while continuing to develop the Flask skill through practice.

## Critical Issue Identified

**Iteration 1 Result:** 6/9 tests passed, 3 failed

**Failures:**
- `test_setup_idempotent` - sqlite3.OperationalError: no such table: accounts
- `test_transfer_with_description` - sqlite3.OperationalError: no such table: transactions  
- `test_balances_updated_correctly` - sqlite3.OperationalError: no such table: accounts

**Root Cause:** Database path resolution mismatch
```python
# WRONG - captures CWD at import time
DB_PATH = os.path.join(os.getcwd(), 'bank.db')

# CORRECT - resolved at each connect() call
DB_PATH = 'bank.db'
```

The app was writing to a different database file than the tests were reading from because:
1. `os.getcwd()` was evaluated at module import time
2. Tests opened separate connections using relative paths
3. CWD may have changed between import and test execution

## Solution Implemented

### 1. Fixed Database Path Resolution
Changed to relative path `'bank.db'` that resolves at connection time, ensuring app and tests always access the same file.

### 2. Maintained Transaction Control
Kept `isolation_level=None` with explicit `BEGIN IMMEDIATE` for atomic operations, preserving the TOCTOU race prevention from iteration 1.

### 3. Preserved Validation Ordering
Maintained two-phase validation:
- Phase 1: Cheap checks without DB access (types, ranges, business rules)
- Phase 2: DB checks inside transaction (existence, balance sufficiency)

### 4. Updated Skill Documentation
Added to `skill/flask/SKILL.md`:
- **Database Path Resolution** section explaining the CWD trap
- **Common Pitfalls** entry #11 documenting this pattern
- Created `ITERATION_2_SUMMARY.md` with detailed analysis

## Verification Results

**All 10 tests pass:**
- ✅ Setup returns 200
- ✅ Setup idempotent (external connection verification)
- ✅ Successful transfer
- ✅ Transfer with description (external connection verification)
- ✅ Balances updated correctly (external connection verification)
- ✅ Missing fields validation
- ✅ Same account transfer validation
- ✅ Negative amount validation
- ✅ Insufficient balance validation
- ✅ Non-existent account validation

## Key Learnings

### Family Invariant
Every SQLite3 case in this family specifies "database in the current working directory". The correct implementation is **always** a relative path string, never an absolute path constructed at import time.

### Why This Trap is Dangerous
1. Only manifests when tests open separate connections
2. Timing-dependent (depends on when CWD changes)
3. Error message ("no such table") doesn't obviously point to path resolution
4. Passes in simple cases where app and tests use the same connection

### Skill Evolution
The Skill now documents:
- Database path resolution pattern (critical for all SQLite3 cases)
- Transaction control with `isolation_level=None`
- Validation ordering principles
- Type validation with bool exclusion
- Common pitfalls specific to Flask stateful services

## Files Modified

1. `/app/solve.py` - Fixed database path resolution
2. `skill/flask/SKILL.md` - Added database path resolution section and pitfall entry
3. `skill/flask/ITERATION_2_SUMMARY.md` - Detailed analysis document

## Conclusion

Iteration 2 successfully identified and fixed the critical database path resolution issue that caused 33% of tests to fail in iteration 1. The fix is minimal (one line change) but the underlying principle is a family-wide invariant that applies to every SQLite3 case. The Skill has been updated to prevent this mistake in future iterations and to document the pattern for other cases in the family.

The solution now correctly implements:
- ✅ Atomic transactions with proper isolation
- ✅ Idempotent setup with external verification
- ✅ Comprehensive validation with proper error codes
- ✅ Database path resolution that works with test harnesses
- ✅ Well-documented patterns in the Skill
