# Bug Fix Summary: Account Propagation Guard

## Issue Identified by Teacher

**Critical bug in Step 4 (Account-number propagation)**: The code was adding ALL names on confirmed target accounts to `target_aliases`, including names that Step 3 had correctly classified as separate entities.

### Failure Scenario

If a future variant places "North West Capital Advisors" on account BUS-30001 (the same account as "North West Capital Group"):

1. **Step 3** correctly classifies "North West Capital Advisors" as a separate entity (functional descriptor: "Advisors")
2. **Step 4** (without fix) iterates over BUS-30001's names and adds "North West Capital Advisors" back into `target_aliases`
3. **Result**: False positive — the excluded entity gets re-included

This violates the task spec: "Advisors, partners, or other separately named entities must remain excluded unless the rows provide consistent evidence that they are the target itself."

## Fix Applied

Added a guard in Step 4 to respect prior exclusion decisions:

```python
# BEFORE (buggy):
for acct in confirmed_accounts:
    for name in account_to_names[acct]:
        target_aliases.add(name)  # ← adds EVERYTHING, even excluded advisors

# AFTER (fixed):
for acct in confirmed_accounts:
    for name in account_to_names[acct]:
        if name not in separate_entities:  # ← respect prior exclusion
            target_aliases.add(name)
```

## Principle

**Classification decisions (Step 3) have higher authority than propagation (Step 4).**

Propagation is only for names that *haven't been classified yet*, not for reversing exclusions. A shared account alone is not sufficient evidence to override a functional-descriptor exclusion.

## Verification

### Synthetic Test Case

Created a test where "North West Capital Advisors" shares BUS-30001 with the target:

**WITHOUT fix**:
- Aliases: ['N.W. Capital Holdings', 'North West Cap. Group', 'North West Capital Advisors', 'North West Capital Group']
- Advisors excluded? **False** ✗

**WITH fix**:
- Aliases: ['N.W. Capital Holdings', 'North West Cap. Group', 'North West Capital Group']
- Advisors excluded? **True** ✓

### v01 Verification

- ✓ 14 transactions correctly filtered
- ✓ Output format correct (JSON array, correct keys, all strings, sorted by date)
- ✓ No excluded entities present
- ✓ All expected aliases included

## Documentation Updates

1. **Step 4 prose**: Added explicit warning about not overriding prior exclusions
2. **Step 4 code**: Added `if name not in separate_entities` guard with comment
3. **Common Pitfalls**: Added pitfall #5 "Propagation overriding exclusion"
4. **Verification Checklist**: Added checklist item for the guard

## Impact

This fix makes the algorithm robust against the `distractor_entity_confusability` axis in the spec, where advisors/partners might share accounts with the target. The skill now correctly handles the hardest family variants.
