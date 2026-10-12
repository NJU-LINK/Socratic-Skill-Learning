# Iteration 2 - Bug Fix: Near-Account Distractor Exclusion

## Issue Discovered from Test Failures

The iteration-1 solver produced 14 rows, but the tests expected only 13 rows. The extra row was:
```json
{"Account Number": "BUS-41877", "Company Name": "N.W. Capital Holdings", "Date": "2024-05-18", ...}
```

## Root Cause Analysis

**The Problem**: BUS-41877 is a "near-account" - it's one character different from BUS-41777 (7→8 at position 6).

**Why It Was Included**: The algorithm recognized "N.W. Capital Holdings" as a target alias, and this alias appeared on both BUS-41777 and BUS-41877. The algorithm incorrectly included ALL accounts of a recognized alias.

**Why It Should Be Excluded**: The task instruction explicitly states: "Account numbers are identifiers, not numbers: preserve them exactly and do not treat one-character-near account numbers as equal."

BUS-41877 is a distractor account designed to test whether the algorithm incorrectly treats near-accounts as equal.

## The Fix

### New Algorithm Step 4: Near-Account Conflict Resolution

When an alias appears on multiple accounts, and those accounts are "near-accounts" (one character different from each other):

1. **Detect conflicts**: Find pairs of candidate accounts that differ by exactly one character
2. **Count evidence**: For each account in the conflict, count how many recognized aliases appear on it
3. **Resolve by evidence strength**: The account with MORE recognized aliases is the "established" target account; the account with FEWER aliases is a "near-account distractor" and must be EXCLUDED

**Example from v01**:
- BUS-41777: appears with "N.W. Capital Hldgs" and "N.W. Capital Holdings" → 2 aliases
- BUS-41877: appears with only "N.W. Capital Holdings" → 1 alias
- BUS-41877 is one character different from BUS-41777 → conflict detected
- BUS-41777 has more aliases → BUS-41777 is established, BUS-41877 is excluded

### New Algorithm Step 5: Account-Based Filtering

Changed the filtering logic from:
```python
# OLD (buggy):
matching_rows = [row for row in all_rows if row['Company Name'] in target_aliases]
```

To:
```python
# NEW (correct):
matching_rows = [row for row in all_rows if row['Account Number'] in confirmed_accounts]
```

**Why**: A row should only be included if its **account number** is confirmed, not just because the company name is a recognized alias. This ensures near-account distractors are excluded even if they have a recognized alias name.

## Verification

**Before fix**: 14 rows, includes BUS-41877 ✗
**After fix**: 13 rows, excludes BUS-41877 ✓

**Test expectations**:
- TARGET_ACCOUNTS = {'BUS-30001', 'BUS-41777'} ✓
- FORBIDDEN_IDENTITIES includes ('N.W. Capital Holdings', 'BUS-41877', '2024-05-18') ✓

## Key Principle

**Account numbers are identifiers, not numbers**. One-character differences matter. When in doubt, prefer the account with stronger evidence (more recognized aliases), and exclude near-account distractors.

## Skill Updates

Updated SKILL.md:
1. Step 4: Added near-account conflict detection and resolution
2. Step 5: Changed filtering to account-based (not name-based)
3. Common Pitfalls: Added pitfall #3 "Near-account distractors"
4. Verification Checklist: Added checks for near-account conflict resolution
