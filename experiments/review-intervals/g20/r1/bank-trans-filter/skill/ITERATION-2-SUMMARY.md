# Iteration 2 - Completion Summary

## What Was Fixed

### Critical Bug: Near-Account Distractor Exclusion

**Problem**: The iteration-1 algorithm included BUS-41877 (a near-account distractor) because "N.W. Capital Holdings" appeared on both BUS-41777 and BUS-41877, and the algorithm incorrectly included ALL accounts of a recognized alias.

**Solution**: Implemented near-account conflict resolution:
1. Detect pairs of candidate accounts that differ by exactly one character
2. Count how many recognized aliases appear on each account
3. Exclude the account with fewer aliases (the near-account distractor)

**Result**: 
- Before: 14 rows (includes BUS-41877) ✗
- After: 13 rows (excludes BUS-41877) ✓

## Skill Updates

### SKILL.md Changes

1. **Step 4**: Added near-account conflict detection and resolution
   - Detect conflicts: accounts differing by exactly one character
   - Resolve by evidence strength: account with more recognized aliases wins
   - Exclude near-account distractors

2. **Step 5**: Changed filtering logic from name-based to account-based
   - OLD: Include rows where company name is a recognized alias
   - NEW: Include rows where account number is in confirmed_accounts
   - This ensures near-account distractors are excluded even if they have a recognized alias name

3. **Common Pitfalls**: Added pitfall #3 "Near-account distractors"
   - When an alias appears on multiple accounts, and one account is one character different from another, the account with FEWER recognized aliases is a distractor and must be excluded

4. **Verification Checklist**: Added checks for near-account conflict resolution

## Test Results

All verification checks pass:
- ✓ 13 transactions (correct count)
- ✓ Accounts: ['BUS-30001', 'BUS-41777'] (correct)
- ✓ BUS-41877 excluded (correct)
- ✓ No forbidden entities present
- ✓ Output format correct (JSON array, correct keys, all strings, sorted by date)

## Key Insights

1. **Account numbers are identifiers, not numbers**: One-character differences matter. BUS-41777 and BUS-41877 are DIFFERENT accounts, even though they differ by only one character.

2. **Evidence-based conflict resolution**: When accounts conflict (near-accounts), use the account with stronger evidence (more recognized aliases) as the established target account.

3. **Account-based filtering**: Filter by account number, not just by company name. A recognized alias on a near-account distractor should NOT cause that account to be included.

## Spec Coverage

✓ **company_identity_signal_variation**: Handles abbreviations, initials, legal-suffix changes, typos, compound words
✓ **transaction_membership_inference**: Propagates identity evidence via shared account numbers, with proper conflict resolution
✓ **distractor_entity_confusability**: Excludes separate entities with functional descriptors, excludes near-account distractors

## Ready for Deployment

The skill package is complete and ready to apply to unseen variants in the bank-trans-filter task family. The algorithm correctly handles the hardest family variants, including near-account distractors.
