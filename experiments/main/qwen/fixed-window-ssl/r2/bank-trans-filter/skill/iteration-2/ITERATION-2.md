# Iteration 2 Summary

## Critical Bug Fixed

**Problem:** BUS-41877 was incorrectly included in the output. It's a near-miss account (one character different from BUS-41777) and should be excluded as a data entry error.

**Root Cause:** The original implementation didn't detect near-miss account numbers. The task instruction states: "Account numbers are identifiers, not numbers: preserve them exactly and do not treat one-character-near account numbers as equal."

## Solution: Collect-Then-Prune Approach

### Why Not Fixpoint-Based Detection?

Initial attempt used fixpoint iteration to check near-misses against `known_target_accounts` as it was being built. This has an **ordering bug**:
- If BUS-41877's anchor row is processed before BUS-41777's anchors, BUS-41877 gets added first
- Then BUS-41777 (the real account) would be blocked as a "near-miss" of BUS-41877
- Result: wrong account excluded

### Collect-Then-Prune Algorithm

**Phase 1: Collect all potential target accounts**
- Scan all rows with score ≥ threshold and no differentiating suffix
- Collect unique account numbers into `potential_accounts` set

**Phase 2: Remove near-misses**
- Compare all accounts against each other
- For each pair of near-miss accounts (edit distance ≤ 1):
  - Count high-confidence rows for each account
  - Remove the account with fewer rows (likely the typo)
- This avoids ordering dependencies

**Phase 3: Propagate with clean account set**
- Use pruned `potential_accounts` as `known_target_accounts`
- Mark all rows on these accounts as target rows
- Apply differentiating suffix logic

### Results

**Before (Iteration 1):**
- 14 rows
- Accounts: BUS-30001, BUS-41777, BUS-41877
- Test failures: 3/4

**After (Iteration 2):**
- 13 rows
- Accounts: BUS-30001, BUS-41777
- BUS-41877 correctly excluded
- Expected to pass all 4/4 tests

## Files Updated

1. **skill/bank-trans-filter/SKILL.md**
   - Section 6: Near-Miss Account Detection and Exclusion
   - Key Principles #6: Exact account matching with near-miss detection
   - Added collect-then-prune algorithm documentation

2. **skill/bank-trans-filter/impl.py**
   - Added `is_near_miss_account()` function (edit distance ≤ 1)
   - Rewrote `filter_transactions()` to use collect-then-prune approach
   - Removed fixpoint-based near-miss checking

## Verification

Output verification confirms:
- ✓ 13 rows (correct count)
- ✓ Accounts: BUS-30001, BUS-41777 (no BUS-41877)
- ✓ Companies: N.W. Capital Holdings, N.W. Capital Hldgs, North West Cap. Group, North West Capital Group
- ✓ No forbidden identities (Advisors/Advisory/Partners)
- ✓ Dates sorted ascending
- ✓ All values are strings
- ✓ Exact CSV keys preserved

## Key Learning

When dealing with data entry errors (typos in identifiers), use **collect-then-prune** instead of incremental checking. This avoids ordering dependencies and uses evidence strength (row count) as a heuristic for correctness.
