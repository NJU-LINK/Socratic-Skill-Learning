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

## Algorithm: Two-Pass Anchor-and-Propagate

The core insight: **compute a graph closure, not a filter**. The target entity's footprint is discovered iteratively.

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

3. **Identify anchors**: rows with similarity ≥ 0.7 to the target
   - These are high-confidence matches that establish the target's identity

4. **Extract anchor accounts**: collect all account numbers from anchor rows

### Phase 2: Propagation and Controlled Discovery

5. **Iterate until fixed point**:
   
   **(a) Propagate by exact account matching only**:
   - Include any row whose account number exactly matches a known account
   - Account numbers are **identifiers, not numbers**: preserve exactly, use exact string equality
   - Do NOT use numeric near-matches or edit distance on accounts
   - Add the row's normalized name to known_names
   
   **(b) Discovery pass (controlled name similarity)**:
   - For remaining rows, check if name is highly similar (≥ 0.8) to any known name variant
   - If so, treat as a new anchor: add its account to known_accounts and include the row
   - This is safer than unrestricted propagation because:
     * The threshold is higher (0.8 vs 0.5), reducing false positives
     * New accounts are discovered through strong name evidence
     * Propagation is still via exact account matching

**Critical invariant**: The propagation loop uses **exact account matching only**. Name similarity is used only in the controlled discovery pass with threshold ≥ 0.8, not in the main propagation loop.

## Critical Invariants

1. **Exact account matching**: Account numbers are string identifiers. `BUS-24192` and `BUS-24193` are different accounts even though they differ by one character.

2. **Name normalization is asymmetric**: Abbreviations and suffixes are expanded/removed for comparison, but the original name is preserved in output.

3. **Distractor detection checks the original target string**: The distractor function checks indicator words (Advisors, Partners, etc.) against the **original target string** (before normalization), not the normalized version. This prevents false positives when the target itself contains indicator words (e.g., "Apex Partners LLC" should not be marked as a distractor).

4. **Propagation is account-based only**: The main propagation loop uses exact account matching. Name similarity is used only in the controlled discovery pass with threshold ≥ 0.8, not in unrestricted propagation.

5. **Output preservation**: All values must be strings preserved exactly from the CSV. Do not parse amounts as numbers or dates as date objects.

## Common Failure Modes

1. **Over-propagation via name similarity**: If you use name similarity with a low threshold (e.g., 0.5) in the propagation loop, you'll include false positives like "Momentum Capital" when the target is "North West Capital". **Fix**: Use exact account matching for propagation, and restrict name similarity to the discovery pass with threshold ≥ 0.8.

2. **Under-propagation via strict thresholds**: If the anchor threshold is too high (e.g., 0.9), you'll miss legitimate variants like "N.W. Capital Holdings" when the target is "North West Capital".

3. **Account number near-matches**: Treating account numbers as numeric values and matching `BUS-24192` with `BUS-24193` via edit distance. This is wrong; accounts are identifiers.

4. **Missing distractor detection**: Including "North West Capital Advisors" because it's similar to "North West Capital". The "Advisors" suffix indicates a separate entity.

5. **Distractor false positives on indicator-containing targets**: If the target is "Apex Partners LLC" and you check distractor indicators against the normalized target (which strips "Partners"), you'll incorrectly mark the target itself as a distractor. **Fix**: Check indicators against the original target string, not the normalized version.

6. **Incorrect output format**: Wrapping the JSON array in an object, parsing amounts as numbers, or sorting incorrectly.

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

**Anchor variants discovered**:
- "North West Cap. Group" → normalized to "north west capital" (similarity 1.0)
- "North West Capital Group" → normalized to "north west capital" (similarity 1.0)
- "N.W. Capital Holdings" → normalized to "north west capital" (similarity 1.0)
- "N.W. Capital Hldgs" → normalized to "north west capital" (similarity 1.0)

**Anchor accounts**: BUS-30001, BUS-41777, BUS-41877

**Distractors excluded**:
- "Northwest Capital Advisors" (BUS-41707) - "Advisors" suffix
- "North West Capital Advisors" (BUS-35001) - "Advisors" suffix
- "North West Capital Advisory" (BUS-30071) - "Advisory" suffix
- "Northwest Capital Partners" (BUS-41770) - "Partners" suffix

**Result**: 14 transactions across 3 accounts, 4 name variants

## Adaptation to New Tasks

To apply this skill to a new dataset:

1. **Identify the target entity** from the task description
2. **Adjust abbreviation expansions** if the dataset uses different abbreviations (e.g., "Intl" → "International")
3. **Adjust distractor indicators** if the dataset has different entity-type suffixes
4. **Tune the anchor threshold** (default 0.7) if needed:
   - Lower (0.6) for more aggressive matching
   - Higher (0.8) for more conservative matching
5. **Run the script** and verify the output

The algorithm is robust to:
- Spelling variations and typos
- Abbreviations and legal-suffix changes
- Multiple accounts per entity
- Scattered rows across the dataset
- Distractor entities with similar names
