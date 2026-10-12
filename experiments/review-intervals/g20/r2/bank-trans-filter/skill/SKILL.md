---
name: bank-trans-filter
description: Filter bank transactions to extract only those belonging to a target company using entity resolution via bipartite graph propagation. Handles name variants, abbreviations, typos, and evidence propagation across accounts.
---

# Bank Transaction Filter Skill

## Purpose
Extract transactions belonging to a target company from a bank transactions CSV, handling:
- Company name variants (spelling, abbreviations, legal suffixes)
- Multiple accounts per company
- Evidence propagation across rows
- Exclusion of similar-but-different entities

## Core Algorithm: Bipartite Graph Propagation

### 1. Parse Target Name
Extract the target company name from the task specification. This is the entity to find.

### 2. Build Bipartite Graph
Create edges between company names and account numbers:
- Each row creates an edge: `company_name ↔ account_number`
- Multiple rows build a graph where names and accounts are nodes

### 3. Seed Target Names
Score each unique company name against the target using token similarity:

**Normalization:**
- Lowercase
- Expand single-letter initials: "N.W." → tokens {n, w}
- Strip punctuation and legal suffixes (Group, Holdings, Hldgs, Corp, LLC, Ltd, Inc, Co, Partners, Advisors, Advisory)
- Tokenize on whitespace

**Matching (two signals — either can trigger seeding):**
- **Token containment**: what fraction of target tokens appear in company tokens (after abbreviation expansion)
- **Fuzzy string ratio**: character-level similarity between normalized name strings (catches spelling drift)
- Seed if EITHER signal passes threshold (containment ≥ threshold OR fuzzy ≥ 0.75)

**Soft-blocking (target-aware):**
- If name contains an exclusion keyword (Advisors, Advisory, Partners) that is NOT part of the target name itself, mark as `PENDING` not `TARGET_NAME`
- Propagation can override this if the name appears on an established target account
- If the target itself contains "Partners" (e.g., "North West Capital Partners"), then "Partners" is not treated as an exclusion keyword for that target

### 4. Propagate (Iterate Until Stable)
```
repeat until no changes:
  for each account:
    if connected to any TARGET_NAME:
      mark as TARGET_ACCOUNT
  
  for each name:
    if connected to any TARGET_ACCOUNT:
      mark as TARGET_NAME (even if previously PENDING/BLOCKED)
```

This implements the spec's rule: "A recognizable company alias can establish an account as belonging to the target; other rows on that established account may then be included even if their alias is shorter."

**Reconciliation behavior**: Propagation also handles the case where one identifier is only trustworthy after reconciling it against the other. If an account is established via one name variant, other rows on that account are included even if their company name is too abbreviated or corrupted to seed independently. The account membership becomes the authoritative evidence.

### 4b. Near-Account Deduplication
After propagation stabilizes, check for near-miss accounts that are likely data entry errors:

```
for each TARGET_ACCOUNT with only 1 row:
  for each other TARGET_ACCOUNT:
    if edit_distance(this_account, other_account) <= 2:
      remove this_account from TARGET_ACCOUNTS
```

**Rationale**: The spec says "Account numbers are identifiers, not numbers: preserve them exactly and do not treat one-character-near account numbers as equal." A single-row account that differs by only 1-2 characters from an established multi-row target account is likely a typo, not a legitimate separate account. Accounts with multiple rows are kept even if near-misses (strong evidence overrides the heuristic).

### 5. Output
Include every row whose **account number** is a TARGET_ACCOUNT. Account membership is the final arbiter — don't filter by name at output time.

## Implementation

Use the provided Python script at `/skill/filter.py`:

```bash
python3 /skill/filter.py \
  --input /app/data/bank_transactions.csv \
  --output /app/data/output.json \
  --target "North West Capital"
```

Optional parameters:
- `--threshold`: Containment similarity threshold (default: 0.6)

The script:
- Reads the CSV
- Builds the bipartite graph
- Seeds target names using token similarity + fuzzy string matching
- Propagates evidence iteratively
- Outputs JSON array sorted by Date ascending
- Preserves all values exactly as strings from CSV

## Key Invariants

1. **Account numbers are exact identifiers** — never fuzzy-match accounts
2. **Evidence propagation is iterative** — single-pass filtering misses indirect evidence
3. **Soft blocks are revocable** — exclusion keywords don't prevent propagation
4. **Output is account-based** — after propagation, include all rows on target accounts
5. **Preserve exact values** — don't modify amounts, dates, or descriptions

## Spec Variations

The skill handles these spec-declared variations:
- **company_identity_signal_variation**: Different name patterns, abbreviations, typos
- **transaction_membership_inference**: Multiple accounts, sparse anchors, indirect evidence
- **distractor_entity_confusability**: Similar names, near-miss accounts, subsidiaries

## Failure Modes to Watch

1. **Single-pass filtering**: Missing rows that only connect via propagation
2. **Hardcoded patterns**: Regex for specific names won't generalize
3. **Fuzzy account matching**: Account numbers must be exact strings
4. **Ignoring soft blocks**: Exclusion keywords should be overridable by propagation
5. **Name-based output filtering**: After propagation, use account membership, not name matching
6. **Suffix-stripping position**: Legal suffixes are stripped only from the END of names (positional heuristic). This works for standard patterns like "Company Name LLC" but could miss matches if suffixes appear mid-name (e.g., "Capital Group Holdings" when target is "Capital Group"). The fuzzy string matching partially defends against this, but be aware in edge cases.
7. **Near-account data entry errors**: A single-row account that differs by 1-2 characters from an established target account is likely a typo. The near-account deduplication step catches these. But accounts with multiple rows are kept even if near-misses (strong evidence).
