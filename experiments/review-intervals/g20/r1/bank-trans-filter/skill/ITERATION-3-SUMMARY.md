# Iteration 3 - Robust Tiebreaker for Near-Account Conflicts

## Status: Iteration 2 passed all 4 tests (score 1.0)

The iteration-2 skill correctly solved v01. This iteration focuses on hardening the near-account conflict resolution for unseen variants.

## Improvement Made

### Robust Tiebreaker for Near-Account Conflicts

**Problem**: The iteration-2 near-account conflict resolution had an incomplete tiebreaker. When two accounts had the same number of recognized aliases, the algorithm said "keep both (conservative approach)" without implementing the additional heuristics mentioned in the prose. This could lead to false positives on harder variants.

**Solution**: Added a 3-level tiebreaker hierarchy:
1. **Primary**: Count of recognized aliases (account with more wins)
2. **Secondary**: Total row count (account with more activity wins)
3. **Tertiary**: Chronological order (account with earliest date wins)
4. **Fallback**: Keep both (very rare edge case)

**Code change**:
```python
# Before (incomplete):
else:
    # Tie: use additional heuristics (e.g., which appears first chronologically)
    # For now, keep both (conservative approach)
    pass

# After (complete):
else:
    # Tie: use additional heuristics
    rows_on_acct1 = len([r for r in all_rows if r['Account Number'] == acct1])
    rows_on_acct2 = len([r for r in all_rows if r['Account Number'] == acct2])
    if rows_on_acct1 > rows_on_acct2:
        confirmed_accounts.discard(acct2)
    elif rows_on_acct2 > rows_on_acct1:
        confirmed_accounts.discard(acct1)
    else:
        dates_acct1 = [r['Date'] for r in all_rows if r['Account Number'] == acct1]
        dates_acct2 = [r['Date'] for r in all_rows if r['Account Number'] == acct2]
        if dates_acct1 and dates_acct2:
            if min(dates_acct1) < min(dates_acct2):
                confirmed_accounts.discard(acct2)
            else:
                confirmed_accounts.discard(acct1)
```

## Verification on v01

The updated algorithm still produces the correct output:
- 13 transactions on accounts BUS-30001 and BUS-41777
- BUS-41877 correctly excluded as near-account distractor
- All forbidden entities excluded
- Output format correct (JSON array, sorted by date, all strings)

## Why This Matters for Unseen Variants

On harder variants in the `distractor_entity_confusability` axis:
- A near-account distractor might have the same number of aliases as the legitimate account
- Without a robust tiebreaker, the algorithm would keep both accounts (false positive)
- With the 3-level tiebreaker, the algorithm can distinguish the legitimate account by activity level or chronological precedence

## Skill Package Status

The skill package is complete and ready for unseen variants:
- ✓ SKILL.md: Complete algorithmic skill with robust tiebreaker
- ✓ All 4 test types covered
- ✓ All 3 spec axes addressed
- ✓ Verified on v01
