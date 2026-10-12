---
name: bank-trans-filter
description: Entity resolution and transaction filtering for bank statements. Identifies all transactions belonging to a target company by propagating identity evidence across name variants and account numbers, while excluding distractor entities.
---

# Bank Transaction Filter

## Problem Class

This skill solves **entity resolution with evidence propagation** for bank transaction datasets where:
- A target company appears under multiple name variants (typos, abbreviations, legal-suffix changes, punctuation differences)
- The target company uses multiple account numbers
- Distractor entities exist with similar names or account numbers that must be excluded
- Identity must be inferred by propagating evidence across rows, not by simple string matching

## Algorithm: Anchor-Propagate with Near-Account Filtering

The core insight: **evidence flows from names to accounts (anchor), then from accounts to rows (propagate)**. Name similarity establishes accounts; exact account matching propagates to rows. No name-based expansion of the account set occurs after anchoring.

### Phase 1: Anchor Discovery (High-Confidence Name Matching)

1. **Normalize all company names**:
   - Lowercase everything
   - Remove punctuation (periods, commas, hyphens, apostrophes)
   - Expand common abbreviations: NW → "north west", N.W. → "north west", Cap → "capital", Hldgs → "holdings"
   - Remove legal suffixes: Group, Holdings, Inc, LLC, Corp, Ltd, Limited, Company, Co, Partners, Services, Systems, Advisory, Advisors
   - Collapse whitespace

2. **Compute similarity** between each normalized name and the target:
   - Token Jaccard: |intersection| / |union| of word sets
   - Sequence matcher ratio (from difflib)
   - Use maximum of both

3. **Identify anchors**: rows with similarity ≥ 0.7 to the target (after distractor check)
   - These are high-confidence matches that establish the target's identity

4. **Extract candidate accounts**: collect all account numbers from anchor rows, counting rows per account

### Phase 1.5: Near-Account Distractor Detection

5. **Detect near-account distractors**:
   - For each pair of candidate accounts, compute edit distance
   - If two accounts differ by ≤ 2 characters (near-miss), they are likely the same account with a typo
   - Keep only the account with MORE rows; discard the other
   - This excludes corrupted/typo account numbers that happen to have matching names

**Example**: BUS-41777 (5 rows) and BUS-41877 (1 row) differ by one character (7→8). BUS-41877 is a near-account distractor and is excluded.

### Phase 2: Exact Account Propagation

6. **Include all rows** whose account number exactly matches a surviving candidate account
   - Account numbers are **identifiers, not numbers**: preserve exactly, use exact string equality
   - Do NOT use numeric near-matches or edit distance on accounts
   - This propagates identity: if account BUS-30001 belongs to the target, all rows on BUS-30001 belong to the target

### Phase 3: Distractor Pruning (Applied Throughout)

7. **Exclude distractors** before and during all phases:
   - Names containing "Advisors", "Advisory", "Partners", "Associates", "Consulting", "Advisers", "Consultants" indicate separate legal entities
   - Check indicator words against the **original target string** (before normalization), not the normalized version
   - This prevents false positives when the target itself contains indicator words (e.g., "Apex Partners LLC")

## Critical Invariants

1. **Exact account matching**: Account numbers are string identifiers. `BUS-24192` and `BUS-24193` are different accounts even though they differ by one character.

2. **One-directional evidence flow**: Name evidence → establishes account (anchor). Account membership → includes rows (propagation). Name similarity is NEVER used to expand the account set after Phase 1.

3. **Near-account distractor detection**: If two candidate accounts are near-misses (edit distance ≤ 2), keep only the one with more rows. This excludes corrupted account numbers.

4. **Distractor detection checks the original target string**: The distractor function checks indicator words against the **original target string** (before normalization), not the normalized version.

5. **Output preservation**: All values must be strings preserved exactly from the CSV. Do not parse amounts as numbers or dates as date objects.

## Common Failure Modes

1. **Discovery pass over-propagation**: If you use name similarity to add NEW accounts after Phase 1 (a "discovery pass"), you'll include near-account distractors like BUS-41877 when the target account is BUS-41777. **Fix**: Remove the discovery pass entirely. Propagation is by exact account matching only.

2. **Missing near-account distractor detection**: If you don't check for near-miss accounts, you'll include corrupted account numbers that happen to have matching names. **Fix**: After Phase 1, check for near-account distractors (edit distance ≤ 2) and keep only the account with more rows.

3. **Under-propagation via strict thresholds**: If the anchor threshold is too high (e.g., 0.9), you'll miss legitimate variants like "N.W. Capital Holdings" when the target is "North West Capital".

4. **Account number near-matches in propagation**: Treating account numbers as numeric values and matching `BUS-24192` with `BUS-24193` via edit distance during propagation. This is wrong; accounts are identifiers.

5. **Missing name-based distractor detection**: Including "North West Capital Advisors" because it's similar to "North West Capital". The "Advisors" suffix indicates a separate entity.

6. **Distractor false positives on indicator-containing targets**: If the target is "Apex Partners LLC" and you check distractor indicators against the normalized target (which strips "Partners"), you'll incorrectly mark the target itself as a distractor. **Fix**: Check indicators against the original target string, not the normalized version.

7. **Incorrect output format**: Wrapping the JSON array in an object, parsing amounts as numbers, or sorting incorrectly.

## Reusable Implementation

The script `scripts/resolve_and_filter.py` implements this algorithm:

```bash
python resolve_and_filter.py <csv_path> <target_entity> <output_path>
```

**Parameters**:
- `csv_path`: Path to the input CSV file
- `target_entity`: The target company name (e.g., "North West Capital")
- `output_path`: Path for the output JSON file

**Output format**:
- JSON array (no wrapper object)
- One object per matching row
- Keys: `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`
- Sorted by `Date` ascending
- All values are strings preserved exactly from CSV

## Example: v01 Task

**Input**: `bank_transactions.csv` with target "North West Capital"

**Phase 1 — Anchor variants discovered** (name similarity ≥ 0.7):
- "North West Cap. Group" → normalized to "north west capital" (similarity 1.0)
- "North West Capital Group" → normalized to "north west capital" (similarity 1.0)
- "N.W. Capital Holdings" → normalized to "north west capital" (similarity 1.0)
- "N.W. Capital Hldgs" → normalized to "north west capital" (similarity 1.0)

**Candidate accounts**: BUS-30001 (8 rows), BUS-41777 (5 rows), BUS-41877 (1 row)

**Phase 1.5 — Near-account distractor detection**:
- BUS-41777 and BUS-41877 differ by one character (edit distance = 1)
- BUS-41777 has 5 rows, BUS-41877 has 1 row
- Keep BUS-41777, discard BUS-41877

**Name-based distractors excluded**:
- "Northwest Capital Advisors" (BUS-41707) - "Advisors" suffix
- "North West Capital Advisors" (BUS-35001) - "Advisors" suffix
- "North West Capital Advisory" (BUS-30071) - "Advisory" suffix
- "Northwest Capital Partners" (BUS-41770) - "Partners" suffix

**Result**: 13 transactions across 2 accounts (BUS-30001, BUS-41777), 4 name variants

## Adaptation to New Tasks

To apply this skill to a new dataset:

1. **Identify the target entity** from the task description
2. **Adjust abbreviation expansions** if the dataset uses different abbreviations (e.g., "Intl" → "International")
3. **Adjust distractor indicators** if the dataset has different entity-type suffixes
4. **Tune the anchor threshold** (default 0.7) if needed:
   - Lower (0.6) for more aggressive matching
   - Higher (0.8) for more conservative matching
5. **Tune the near-account threshold** (default 2) if needed:
   - Lower (1) for stricter near-account detection
   - Higher (3) for more lenient detection
6. **Run the script** and verify the output

The algorithm is robust to:
- Spelling variations and typos
- Abbreviations and legal-suffix changes
- Multiple accounts per entity
- Scattered rows across the dataset
- Distractor entities with similar names
- Near-account distractors (corrupted account numbers)
