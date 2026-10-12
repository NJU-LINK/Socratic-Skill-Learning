# Testing Summary

## v01 Data Test
**Target**: "North West Capital"  
**Result**: ✅ 13 rows (correct)

**Accounts identified**:
- BUS-30001 (8 rows)
- BUS-41777 (5 rows)

**Company name variants captured**:
- North West Cap. Group
- North West Capital Group
- N.W. Capital Holdings
- N.W. Capital Hldgs

**Correctly excluded**:
- North West Capital Advisors (BUS-35001) — separate entity, exclusion keyword
- North West Capital Advisory (BUS-30071) — separate entity, exclusion keyword
- Northwest Capital Advisors (BUS-41707) — separate entity, exclusion keyword
- Northwest Capital Partners (BUS-41770) — separate entity, exclusion keyword
- N.W. Capital Holdings on BUS-41877 — near-miss account (edit distance 1 from BUS-41777), single row → likely data entry error

## Near-Account Detection Test
**Test data**: Single-row account that is a near-miss of established target account
```
North West Capital Group, BUS-30001 (2 rows)
N.W. Capital Holdings, BUS-30002 (1 row)  ← edit distance 1 from BUS-30001
```

**Result**: ✅ BUS-30002 correctly excluded (single row + near-miss)

**Test data**: Multi-row account that is a near-miss
```
North West Capital Group, BUS-30001 (2 rows)
N.W. Capital Holdings, BUS-30002 (2 rows)  ← edit distance 1 from BUS-30001
```

**Result**: ✅ BUS-30002 correctly included (strong evidence overrides near-miss heuristic)

**Test data**: Single-row account that is NOT a near-miss
```
North West Capital Group, BUS-30001 (2 rows)
N.W. Capital Holdings, BUS-99999 (1 row)  ← very different from BUS-30001
```

**Result**: ✅ BUS-99999 correctly included (not a near-miss)

## Typo Handling Test
**Test data**: Variants with spelling errors
- "Noth West Capital" (missing 'r')
- "North Wst Captial" (two typos)
- "Northwest Capitel" (typo in Capital)

**Result**: ✅ All 4 variants correctly matched via fuzzy string ratio

## False Positive Test
**Test data**: Different companies with similar words
- Momentum Capital
- Northern Light Energy
- Silverstone Financial

**Result**: ✅ All correctly rejected (only "North West Capital Group" matched)

## Propagation Override Test
**Test data**: Exclusion keyword on established target account
```
North West Capital Group, BUS-30001
North West Capital Advisors, BUS-30001  ← has exclusion keyword
```

**Result**: ✅ Advisors row correctly included via propagation override

## Target-Aware Exclusion Keyword Test
**Test data**: Target name itself contains an exclusion keyword
```
Target: "North West Capital Partners"
North West Capital Partners, BUS-50001  ← "Partners" is part of target
N.W. Capital Partners, BUS-50001
North West Capital Advisors, BUS-50003  ← "Advisors" is NOT in target
```

**Result**: ✅ "Partners" not treated as exclusion keyword (it's in the target).
"Advisors" correctly soft-blocked (not in target).

## Algorithm Verification

### Token Containment
- Target tokens: {north, west, capital}
- "N.W. Capital Holdings" → {n, w, capital} → expands to {north, west, capital} → 100% match ✅
- "North West Cap. Group" → {north, west, cap} → cap expands to capital → 100% match ✅

### Fuzzy String Matching
- "North Wst Captial" → fuzzy ratio 0.85 → passes 0.75 threshold ✅
- "Momentum Capital" → fuzzy ratio 0.45 → below threshold ✅

### Iterative Propagation
- Step 1: Seed target names via token/fuzzy matching
- Step 2: Mark accounts connected to target names
- Step 3: Mark names connected to target accounts (overrides soft blocks)
- Repeat until stable

### Near-Account Deduplication
- Step 4: For each target account with only 1 row:
  - If edit distance ≤ 2 to another target account → exclude
  - This catches data entry errors like BUS-41877 (typo of BUS-41777)
- Accounts with multiple rows are kept even if near-misses

### Soft Blocking
- Names with "Advisors/Advisory/Partners" → marked PENDING
- If PENDING name appears on TARGET_ACCOUNT → promoted to TARGET_NAME
- Implements spec rule: "consistent evidence that they are the target itself"

## Edge Cases Handled

1. **Abbreviation expansion**: N.W. → North West
2. **Compound words**: Northwest → North + West
3. **Legal suffixes**: Group, Holdings, Hldgs stripped correctly
4. **Punctuation**: Periods, commas handled in normalization
5. **Case insensitivity**: All matching is case-insensitive
6. **Exact account matching**: Account numbers never fuzzy-matched
7. **Multiple accounts**: Same company can have multiple accounts
8. **Evidence propagation**: Indirect connections discovered iteratively
9. **Near-account deduplication**: Single-row near-misses excluded as likely typos
10. **Strong evidence override**: Multi-row near-misses kept
11. **Target-aware exclusion keywords**: If the target name itself contains "Partners" (e.g., "North West Capital Partners"), then "Partners" is not treated as an exclusion keyword. Only exclusion keywords NOT present in the target name trigger soft-blocking.
