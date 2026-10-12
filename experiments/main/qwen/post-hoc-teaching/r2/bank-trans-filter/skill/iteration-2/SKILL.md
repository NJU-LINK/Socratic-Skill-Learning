---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a target company,
  using evidence-proportional reconciliation across name and account dimensions.
  Strong matches (compact containment) establish accounts ordered by evidence strength;
  weak matches (edit distance) only ride along on established accounts. Near-miss
  account numbers are rejected only when their evidence is disproportionately weak
  relative to established accounts, allowing legitimate separate accounts with
  coincidentally similar numbers to be accepted. Handles abbreviation expansion,
  legal-suffix normalization, token-overlap pre-filtering, and exclusion of
  advisors/partners/subsidiaries.
---

# Bank Transaction Filter

## Task Summary

Given a CSV of bank transactions and a target company name, extract all transactions
belonging to that company. The same company may appear under multiple name variants
and account numbers. Write the result as a sorted JSON array.

## Input / Output Contract

- **Input**: CSV file at `/app/data/bank_transactions.csv` with columns including
  `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`.
- **Output**: JSON array at `/app/data/output.json` — one object per matching row,
  with exactly the CSV column keys, sorted by `Date` ascending, all values as strings
  preserved exactly from the CSV.

## Algorithm: Evidence-Proportional Reconciliation

### Core Principle

When a row's name says "target" but its account is a near-miss of an established
account, we have **conflicting evidence across two identifier dimensions**:
- **Name evidence**: strong match → "this IS the target company"
- **Account evidence**: near-miss → "this account number might be corrupted"

The correct decision depends on the **weight of evidence behind the near-miss account**,
not just its existence. A near-miss with strong independent evidence (multiple rows)
is likely a legitimate separate account with a coincidentally similar number. A
near-miss with only 1-2 rows is likely a typo.

**Trust an identifier only when the corroborating evidence on the OTHER identifier
dimension is strong enough to override the concern raised by this dimension.**

### Layer 1: Name Matching with Confidence Tiers

For each row, determine whether its `Company Name` matches the target, returning
one of three results: `'strong'`, `'weak'`, or `None`.

**Normalization pipeline** (applied to both target name and each company name):
1. **Lowercase** the string
2. **Remove punctuation**: replace `.,;:'"()-/&` with spaces
3. **Collapse whitespace** to single spaces
4. **Expand abbreviations** using a dictionary (e.g., `nw` → `north west`,
   `cap` → `capital`, `hldgs` → `holdings`, `co` → `company`, `ltd` → `limited`)
5. **Strip legal suffixes** from the end of the token list (e.g., `group`,
   `holdings`, `llc`, `inc`, `ltd`, `corp`, `trust`, `fund`)

**Matching logic** (applied after normalization):

1. **Exclusion check** → `None`: If the company name contains words like `advisors`,
   `advisory`, `partners`, `partnership`, `subsidiary`, `affiliates`, `division`,
   `branch` → REJECT. These indicate a *different* entity even if other words
   overlap with the target.

2. **STRONG — Compact containment** → `'strong'`: Join the core tokens into a
   single string with no spaces. If the target's compact form is a substring of
   the company's compact form → STRONG MATCH. This handles space variations
   ("North West" vs "Northwest"), abbreviation expansions, and legal suffixes.
   **Strong matches can establish accounts.**

3. **Token overlap pre-filter** → `None`: Before attempting edit distance, require
   that the company shares at least 50% of the target's core tokens. This prevents
   unrelated companies with similar-length compact strings from matching.

4. **WEAK — Edit distance fallback** → `'weak'`: Compute Levenshtein distance
   between the two compact forms. If distance ≤ max(2, len(target_compact) // 6)
   → WEAK MATCH. This handles character-level typos.
   **Weak matches cannot establish accounts; they only ride along.**

### Layer 2: Account Establishment with Evidence-Proportional Reconciliation

**Key insight**: Not all accounts that pass name matching should be established.
A typo account number (e.g., BUS-41877 when BUS-41777 is the real account) may
pass name matching but should not establish a new account if its evidence is weak.

**Evidence-strength ordering**: Accounts are established in order of how many
strong-match rows they have. Accounts with more corroborating evidence are
established first. This ensures that the real account (with many rows) is
established before a typo account (with few rows), regardless of chronological
order in the data.

**Evidence-proportional near-miss rejection**: When considering a new account
for establishment, check if its account number is a near-miss (Levenshtein
distance ≤ 2) of any already-established account. If so, reject it **only if**
its evidence is disproportionately weak:

```python
if new_count < max(2, est_count * 0.5):
    # Reject: evidence too weak to override near-miss concern
else:
    # Accept: strong independent evidence suggests legitimate separate account
```

This implements the reconciliation principle:
- **Scenario A** (v01): BUS-41877 has 1 row, BUS-41777 has 5 rows → reject
  (1 < max(2, 2.5) = 2.5)
- **Scenario B** (hypothetical): BUS-41877 has 6 rows, BUS-41777 has 5 rows → accept
  (6 >= 2.5, strong independent evidence)

**Algorithm**:
1. Group all strong-match rows by account number
2. Sort accounts by number of strong-match rows (descending)
3. For each account (most evidence first):
   - If it's a near-miss of an established account AND its evidence is weak → SKIP
   - Otherwise → ESTABLISH (add to established set, include all its rows)
4. Include ALL rows on established accounts (even non-matching names)

### Layer 3: Weak Match Integration and Fallback

**Weak matches**: After strong accounts are established, include any weak-match
rows that are on established accounts. (In practice, these are already included
via account propagation, but this documents the intent.)

**Fallback**: If no strong matches exist at all, promote weak matches to
account-establishing status (with the same evidence-proportional reconciliation).
This handles edge cases where the target only appears with typos.

### Layer 4: Output Assembly

1. Collect all matching row indices
2. Build JSON objects with exactly the CSV column keys
3. Sort by `Date` ascending (lexicographic on ISO date strings)
4. Write as a JSON array (no top-level wrapper)

## Why Evidence-Proportional Reconciliation?

**Without reconciliation** (flat near-miss rejection):
- BUS-41877 with 6 strong-match rows would be rejected as a near-miss of BUS-41777
- This is incorrect: 6 rows of independent name evidence strongly suggests a
  legitimate separate account with a coincidentally similar number

**With reconciliation**:
- BUS-41877 with 1 row is rejected (evidence too weak to override near-miss concern)
- BUS-41877 with 6 rows is accepted (strong independent evidence overrides near-miss concern)

The spec explicitly requires: *"cases where one identifier is trustworthy only after
reconciling it against the other."* Evidence-proportional reconciliation implements
this by trusting an identifier when the corroborating evidence on the OTHER identifier
dimension is strong enough.

## Concrete Examples

### Example 1: v01 (typo account)

- BUS-41777 has 5 strong-match rows
- BUS-41877 has 1 strong-match row (near-miss, differs by 1 character)
- Reconciliation: 1 < max(2, 5*0.5) = 2.5 → reject BUS-41877
- Result: 13 transactions from BUS-30001 and BUS-41777

### Example 2: Hypothetical (legitimate separate account)

- BUS-41777 has 5 strong-match rows
- BUS-41877 has 6 strong-match rows (near-miss, differs by 1 character)
- Reconciliation: 6 >= max(2, 5*0.5) = 2.5 → accept BUS-41877
- Result: 11 transactions from both BUS-41777 and BUS-41877

## Key Design Decisions

### Why evidence-strength ordering instead of chronological?

If a typo account appeared first chronologically, chronological ordering would
establish it first, then reject the real account as a near-miss. Evidence-strength
ordering always establishes the account with more corroborating evidence first,
regardless of chronological order.

### Why edit distance ≤ 2 for near-miss accounts?

Account numbers like "BUS-41777" and "BUS-41877" differ by 1 character. A
threshold of 2 catches single-character typos and transpositions while not
being so aggressive as to reject legitimately different accounts.

### Why the threshold `max(2, est_count * 0.5)`?

- **Minimum of 2**: Even if the established account has only 1 row, we require
  at least 2 rows to override a near-miss concern (1 row is too weak)
- **50% ratio**: If the established account has 10 rows, the near-miss needs
  at least 5 rows to be accepted. This scales with the strength of the
  established account's evidence.

### Why compact containment instead of token-set intersection?

Token-set intersection would match "Northern Light Energy" against "North West
Capital" because "north" is in both token sets. Compact containment avoids this:
- Target compact: `northwestcapital`
- "Northern Light Energy" compact: `northernlightenergy`
- `northwestcapital` NOT in `northernlightenergy` → no match ✓

### Why exclusion words?

Companies like "North West Capital Advisors" share most words with the target
but are *separate entities*. The exclusion check prevents these from matching
even though compact containment would succeed (since `northwestcapital` IS a
substring of `northwestcapitaladvisors`).

## Abbreviation Dictionary

The script includes abbreviations for:
- **Directional**: nw→north west, ne→north east, sw→south west, se→south east
- **Financial**: cap→capital, hldgs→holdings, fin→financial, inv→investment
- **Entity types**: co→company, corp→corporation, inc→incorporated, ltd→limited
- **Operational**: svc→service, mgmt→management, tech→technology, sys→systems
- **Industry**: mfg→manufacturing, pharm→pharmaceuticals, aero→aerospace

## Variation Dimensions (from spec)

1. **Company identity signal variation**: Different severity of spelling drift,
   abbreviations, legal-suffix changes, partial-name matches, identifier corruption.
   → Handled by: normalization + abbreviation expansion + two-tier matching.

2. **Transaction membership inference**: Multiple accounts per company, sparse anchor
   rows, indirect entity membership, cases where one identifier is trustworthy only
   after reconciling it against the other.
   → Handled by: evidence-proportional reconciliation + account propagation from
   strong anchors; weak matches ride along.

3. **Distractor entity confusability**: Non-target companies with overlapping names,
   near-miss account numbers, subsidiaries/partners.
   → Handled by: exclusion words + token overlap pre-filter + evidence-proportional
   near-miss rejection + exact account matching.

## Usage

```bash
python3 solve.py "Target Company Name"
python3 solve.py "Target Company Name" /path/to/input.csv /path/to/output.json
TARGET_NAME="Target Company Name" python3 solve.py
```

## Edge Cases

1. **No strong matches**: Fallback promotes weak matches to account-establishing
   (with evidence-proportional reconciliation).
2. **Target name contains exclusion words**: Exclusion only applies to data rows,
   not the target name itself.
3. **Account number shared by multiple entities**: Account numbers are exact strings;
   no fuzzy matching. Shared accounts would include all rows.
4. **Very short target names**: Edit distance threshold scales with target length.
5. **Typo account appears first chronologically**: Evidence-strength ordering
   ensures the account with more rows is established first.
6. **Legitimate near-miss account with strong evidence**: Evidence-proportional
   reconciliation accepts it when evidence is strong enough (>= 50% of established
   account's row count, minimum 2 rows).
7. **Multiple legitimate accounts with similar numbers**: Each is evaluated
   independently; those with sufficient evidence are accepted.
