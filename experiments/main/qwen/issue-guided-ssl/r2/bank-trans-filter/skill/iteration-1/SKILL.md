---
name: bank-trans-filter
description: Filter bank transactions to extract only those belonging to a target company using entity resolution via two-phase evidence propagation (name-based anchoring + account-based propagation) with distractor discrimination.
---

# Bank Transaction Filter Skill

## Problem Family

This skill addresses the task of filtering bank transaction records to extract only those belonging to a specific target company. The challenge lies in entity resolution: the same company may appear under multiple name variants (abbreviations, spelling variations, legal suffix changes) and multiple account numbers. Additionally, similar-looking company names or account numbers may belong to different entities and must be excluded.

## Core Algorithm: Two-Phase Evidence Propagation

The solution uses a graph-based entity resolution approach with two interleaved phases:

### Phase A: Anchor Discovery (Name-Based)

1. **Normalize the target company name**: lowercase, expand common abbreviations (e.g., "Cap." → "Capital", "N.W." → "North West", "Hldgs" → "Holdings"), remove punctuation
2. **Extract core tokens**: strip generic legal suffixes (Group, Holdings, Inc, LLC, Corp, Ltd, etc.) to get the core identity tokens
3. **Identify distinguishing suffixes**: terms like "Advisors", "Advisory", "Partners", "Consulting", "Management" indicate separate legal entities and should NOT be stripped
4. **Scan all rows**: for each row, normalize the company name and check if its core tokens match the target using two-layer matching:
   - **Layer 1 (Exact)**: Token-set intersection - fast and precise for clean data
   - **Layer 2 (Fuzzy)**: Character-bigram similarity (Dice coefficient) - handles typos and spelling drift like "Nrth Wst Capital" or "North Wset Cpital"
   - A name matches if ≥80% of target core tokens are present (exact) or have ≥55% character similarity (fuzzy)
5. **Collect anchor rows and their account numbers**

### Phase B: Account Propagation (Account-Based)

1. **For each target account discovered in Phase A**: find all rows sharing that account number
2. **Include rows even with shorter/ambiguous names** if they don't contain distinguishing suffixes that indicate a separate entity
3. **Iterate until convergence**: newly discovered rows may confirm additional account numbers

### Critical Rules

- **Exact account matching only**: Account numbers are identifiers, not numbers. Never use fuzzy matching or numeric comparison. "BUS-30001" ≠ "BUS-30071" even though they differ by one character.
- **Legal suffix discrimination**: Generic structural suffixes (Group, Holdings, Inc, LLC) indicate the same entity. Business activity suffixes (Advisors, Partners, Advisory) indicate separate entities.
- **Abbreviation handling**: Common abbreviations must be expanded before comparison (N.W. → North West, Cap. → Capital, Hldgs → Holdings).
- **Word boundary variations**: "Northwest" vs "North West" may indicate different entities when combined with other signals (different accounts, distinguishing suffixes).

## Implementation

The skill is implemented as a Python script that:

1. Reads the CSV file preserving all values as strings
2. Applies two-phase evidence propagation to identify target rows
3. Outputs a JSON array sorted by Date ascending
4. Preserves all field values exactly as they appear in the CSV

### Usage

```python
python3 solve.py <target_company_name> <input_csv> <output_json>
```

Example:
```python
python3 solve.py "North West Capital" /app/data/bank_transactions.csv /app/data/output.json
```

## Key Considerations for Unseen Variants

### Company Identity Signal Variation

The skill must handle:
- **Severe spelling drift**: typos in company names (e.g., "Mounta5n" vs "Mountain", "Nrth" vs "North")
- **Abbreviations and legal-suffix changes**: "Cap." for "Capital", "N.W." for "North West", "Hldgs" for "Holdings"
- **Partial-name matches**: short aliases that are substrings of the target name
- **Identifier corruption**: typos in account numbers (treat as different accounts)
- **Cross-reconciliation**: one identifier trustworthy only after reconciling with the other

### Two-Layer Name Matching Strategy

The name matching uses two layers to balance precision and recall:

**Layer 1: Exact Token-Set Intersection (Primary)**
- Fast and precise for clean data
- Requires exact token matches after normalization
- Example: "North West Capital Group" matches target "North West Capital" because core tokens {north, west, capital} match exactly

**Layer 2: Character-Bigram Similarity (Fallback)**
- Handles typos and spelling drift using Dice coefficient on character bigrams
- For each target token, finds the best-matching variant token
- Coverage = fraction of target tokens with at least one variant token above 55% similarity
- Example: "Nrth West Capital" with tokens {nrth, west, capital}:
  - "nrth" vs "north" → 57% similarity ✓
  - "west" vs "west" → 100% similarity ✓
  - "capital" vs "capital" → 100% similarity ✓
  - Coverage: 3/3 = 100% (above 80% threshold, accepted)
- Example: "Nrth Wst Cpital" with tokens {nrth, wst, cpital}:
  - "nrth" vs "north" → 57% similarity ✓
  - "wst" vs "west" → 40% similarity ✗ (too short, below 55% threshold)
  - "cpital" vs "capital" → 73% similarity ✓
  - Coverage: 2/3 = 67% (below 80% threshold, rejected)
- This prevents false positives while catching genuine typos

**Threshold rationale:**
- Token threshold: 55% - catches common typos like "nrth" → "north" (57%) while rejecting very short tokens like "wst" → "west" (40%)
- Coverage threshold: 80% - requires most target tokens to match, preventing false positives from partial matches

**Why not purely fuzzy?**
- Character-level matching alone can match unrelated companies
- Two-layer approach: exact matching for precision, fuzzy fallback for recall
- Distinguishing suffixes (Advisors, Partners) are never stripped, even with fuzzy matching

### Transaction Membership Inference

The skill must handle:
- **Multiple accounts per company**: a company may have several account numbers
- **Account reuse patterns**: same account may appear with different name variants
- **Sparse anchor rows**: some rows establish entity membership indirectly
- **Evidence propagation**: identity evidence must propagate across rows, not just filter by one literal string

### Distractor Entity Confusability

The skill must handle:
- **Partial name overlap**: non-target companies with names partially overlapping the target
- **Near-miss account numbers**: accounts differing by one or two characters from target accounts
- **Subsidiaries or partners**: related but legally separate entities
- **High precision requirement**: distinguishing genuine target evidence from superficially similar rows

## Testing Strategy

When testing the skill:

1. **Verify anchor discovery**: check that all name variants of the target are identified
2. **Verify account propagation**: check that all rows on target accounts are included
3. **Verify distractor exclusion**: check that similar-looking entities are excluded
4. **Verify exact account matching**: check that near-miss accounts are not conflated
5. **Verify output format**: check JSON structure, sorting, and string preservation

## Common Pitfalls

1. **Fuzzy account matching**: Never treat "BUS-30001" and "BUS-30071" as the same account
2. **Over-stripping suffixes**: Don't strip "Advisors" or "Partners" - they indicate separate entities
3. **Under-expanding abbreviations**: Always expand "N.W.", "Cap.", "Hldgs" before comparison
4. **Hardcoding target specifics**: The skill must be parameterized on the target name, not hardcoded to specific variants
5. **Ignoring evidence propagation**: Don't just filter by name - propagate through accounts
