---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a target company,
  using two-tier entity resolution: strong matches (compact containment) establish
  accounts for propagation, while weak matches (edit distance) only ride along on
  already-established accounts. Handles abbreviation expansion, legal-suffix
  normalization, typo tolerance, token-overlap pre-filtering, and exclusion of
  advisors/partners/subsidiaries that share partial name overlap.
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

## Algorithm: Two-Tier Confidence Anchoring

The key insight is that **not all name matches should have equal power to establish
accounts**. A false positive in anchor detection cascades: one bad match establishes
an account, and then every row on that account gets included. The solution uses
two confidence tiers to prevent this.

### Phase 1: Name Matching with Confidence Tiers

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

### Phase 2: Account Propagation (Two-Pass)

**Pass 1 — Strong matches establish accounts:**
- Collect all `Account Number` values from strong-match rows → **established accounts**
- Include ALL rows whose `Account Number` is in the established accounts set
  (regardless of their name match tier)

**Pass 2 — Weak matches ride along:**
- For rows not already included: if a row is a weak match AND its account is
  in the established accounts set, include it
- (In practice, these rows are already included via Pass 1 since their account
  is established; Pass 2 documents the intent)

**Fallback:** If no strong matches are found at all, promote weak matches to
account-establishing status. This handles edge cases where the target only
appears with typos.

### Phase 3: Output Assembly

1. Collect all matching row indices
2. Build JSON objects with exactly the CSV column keys
3. Sort by `Date` ascending (lexicographic on ISO date strings)
4. Write as a JSON array (no top-level wrapper)

## Why Two Tiers?

**Without tiers** (v1 approach): A typo match like "Summit Investmnt" on a new
account would establish that account, and all 40+ rows on it would be included —
even rows from "Summit Investment Advisors" that should be excluded.

**With tiers** (v2 approach): "Summit Investmnt" is a weak match (edit distance
only, no containment). It cannot establish its account. Only rows from strong
matches (containment) can establish accounts. This prevents false-positive
cascading through account propagation.

## Key Design Decisions

### Why compact containment instead of token-set intersection?

Token-set intersection would match "Northern Light Energy" against "North West
Capital" because "north" is in both token sets. Compact containment avoids this:
- Target compact: `northwestcapital`
- "Northern Light Energy" compact: `northernlightenergy`
- `northwestcapital` NOT in `northernlightenergy` → no match ✓

### Why token overlap pre-filter before edit distance?

Without it, two unrelated companies with similar-length compact strings could
match via edit distance. Example: "Tech Dynamics" vs "Tech Divisions" — same
prefix, different entity, but compact strings might be close enough. The token
overlap check ensures at least half the target's words are present before
attempting edit distance.

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
   rows, indirect entity membership.
   → Handled by: account propagation from strong anchors; weak matches ride along.

3. **Distractor entity confusability**: Non-target companies with overlapping names,
   near-miss account numbers, subsidiaries/partners.
   → Handled by: exclusion words + token overlap pre-filter + exact account matching.

## Usage

```bash
python3 solve.py "Target Company Name"
python3 solve.py "Target Company Name" /path/to/input.csv /path/to/output.json
TARGET_NAME="Target Company Name" python3 solve.py
```

## Edge Cases

1. **No strong matches**: Fallback promotes weak matches to account-establishing.
2. **Target name contains exclusion words**: Exclusion only applies to data rows,
   not the target name itself.
3. **Account number shared by multiple entities**: Account numbers are exact strings;
   no fuzzy matching. Shared accounts would include all rows.
4. **Very short target names**: Edit distance threshold scales with target length.
