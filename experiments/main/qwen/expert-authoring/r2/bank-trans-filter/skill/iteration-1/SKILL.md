---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to keep only rows belonging to a target company
  whose identity must be inferred through entity resolution. Handles name
  variants (abbreviations, punctuation drift, legal-suffix changes, typos),
  account-number typos, and distractor entities with overlapping names.
  Uses evidence propagation: once a company alias establishes an account as
  belonging to the target, other rows on that account are included if their
  names are consistent with the target.
---

# Bank Transaction Filter — Entity Resolution Skill

## Problem

Given a CSV of bank transactions and a target company name, extract every
transaction that belongs to that company. The target company appears under
multiple name variants and account-number variants with typos. Other companies
may have names that partially overlap the target (subsidiaries, partners,
advisors) and must remain excluded.

## Input

- CSV at `/app/data/bank_transactions.csv`
- Columns: `Company Name`, `Account Number`, `Date`, `Amount`,
  `Transaction Type`, `Description`
- Target company name stated in the task prompt (e.g., "North West Capital")

## Output

- JSON array at `/app/data/output.json`
- One object per matching row with exactly the CSV column keys
- All values preserved as strings exactly from the CSV
- Sorted by `Date` ascending

---

## Strategy

### 1. Parse the CSV

Use Python `csv.DictReader` to read all rows. Preserve every field as an
exact string — no numeric conversion on `Amount` or `Account Number`.

### 2. Normalize names for comparison

Build a normalized form of each company name for fuzzy matching:

1. Lowercase the name.
2. Remove all punctuation (periods, commas, hyphens, apostrophes, ampersands).
3. Collapse whitespace and split into a set of tokens.
4. Remove common legal/structural suffixes:
   `llc, inc, corp, corporation, ltd, limited, company, co, group, holdings,
   hldgs, services, service, solutions, systems, industries, technologies,
   technology, tech, partners, advisors, advisory, consulting, consultancy`.

> **Why strip suffixes?** "North West Capital Group" and "N.W. Capital
> Holdings" are the same entity despite different suffixes. The suffixes
> "Group" and "Holdings" are generic structural words. But "Advisors",
> "Advisory", and "Partners" also appear in this list — they are stripped
> during normalization but then checked separately in step 4.

### 3. Identify target-matching name variants

For each unique company name in the dataset, compute a **core-token overlap**
score against the target name:

```
target_core = tokens(normalize(target_name))   # e.g., {"north", "west", "capital"}
name_core   = tokens(normalize(company_name))  # after suffix removal

score = |name_core ∩ target_core| / |name_core|
```

A name is a **strong match** to the target when **both** conditions hold:

- `score >= 0.75` (at least 75 % of the name's core tokens match the target)
- The name does **not** carry a **disqualifying suffix** that signals a
  separate entity.

**Disqualifying suffixes** (applied to the *original* name, before
normalization): `Advisors`, `Advisory`, `Partners`, `Partner`.

> **Rationale:** "Northwest Capital Advisors" has 67 % core overlap and
> carries the disqualifying suffix "Advisors" → excluded. "North West Cap.
> Group" has 100 % core overlap and no disqualifying suffix → included.
> "N.W. Capital Holdings" has 75 % core overlap (3 of 4 tokens after
> normalization) and no disqualifying suffix → included.

**Abbreviation handling:** Initial-style abbreviations like "N.W." expand
when punctuation is removed to "nw", which is a single token. Because
"nw" does not appear in `{"north", "west", "capital"}`, the overlap score
would be low. To handle this, add an **abbreviation expansion** step before
scoring: if a token looks like an initial (1-2 characters), try splitting
the target name into initials and matching. Concretely:

- "N.W." → "nw" → compare as bigram against target initials "n" + "w"
- If the initials of the target ("n", "w", "c") are all present as
  substrings of the name's tokens, treat the overlap as high.

A simpler alternative: compute `difflib.SequenceMatcher` ratio between
the stripped names (with suffixes removed) and use a threshold of ~0.65.
This naturally handles abbreviation and spacing variants. **Use both** the
token-overlap score and the SequenceMatcher ratio, taking the maximum.

### 4. Establish target accounts

Collect the set of account numbers used by rows whose names are strong
matches to the target:

```
target_accounts = { row["Account Number"] for row in rows
                    if is_strong_match(row["Company Name"], target_name) }
```

### 5. Propagate identity through accounts

Any row whose account number is in `target_accounts` is a candidate for
inclusion, even if its name is a weaker match. Include such a row when:

- Its name does **not** carry a disqualifying suffix, AND
- Its normalized name shares at least one core token with the target
  (i.e., it is not a completely unrelated entity that happens to share
  an account — which should not happen in clean data but guards against
  coincidence).

### 6. Handle account-number typos

After establishing the primary match set, scan remaining unmatched rows
for potential account-number typos. A row is a **typo candidate** if:

- Its company name is a strong match to the target (same criteria as
  step 3), AND
- Its account number has edit distance ≤ 2 from a known target account,
  AND no other established entity (different name cluster) also uses that
  account.

Include such rows — the name evidence plus near-miss account is strong
enough.

> **Caution from spec:** "Account numbers are identifiers, not numbers:
> preserve them exactly and do not treat one-character-near account
> numbers as equal." This means we do NOT merge accounts. We only use
> the near-miss as additional evidence that a row with a strong name
> match truly belongs to the target (likely a data-entry typo).

### 7. Build output and sort

- Collect all included rows.
- Sort by `Date` ascending (ISO date strings sort lexicographically).
- Write as a JSON array to `/app/data/output.json` with `json.dumps(...,
  indent=2, ensure_ascii=False)`.

---

## Decision Rules Summary

| Condition | Action |
|---|---|
| Name core-token overlap ≥ 0.75 with target AND no disqualifying suffix | **Include** |
| Name is strong match AND account is a known target account | **Include** |
| Account is a known target account AND name has ≥ 1 core token overlap AND no disqualifying suffix | **Include** (propagation) |
| Name is strong match AND account edit-distance ≤ 2 from a target account AND account not used by another entity | **Include** (typo recovery) |
| Name has disqualifying suffix (Advisors/Advisory/Partners) | **Exclude** regardless of overlap |
| Name overlap < 0.75 and no qualifying account link | **Exclude** |

---

## Self-Verification Checklist

After producing the output, verify:

1. **Account consistency:** Every output row's account number appears in
   the target-account set OR was included via the typo-recovery rule with
   a documented justification.
2. **No distractors:** No output row has a company name containing
   "Advisor", "Advisory", "Partner", or any other disqualifying suffix.
3. **No near-miss accounts wrongly merged:** If two different account
   numbers appear in the output, they must both be justified independently
   by name evidence.
4. **Sorted order:** Output dates are non-decreasing.
5. **Exact values:** Every field in every output object is an exact
   string copy of the corresponding CSV cell.
6. **Row count sanity:** The number of output rows is plausible given
   the number of rows with strong name matches and their account groups.

---

## Execution

Run the solution script:

```bash
python3 /path/to/skill/bank-trans-filter/scripts/solve.py
```

The script reads from `/app/data/bank_transactions.csv` and writes to
`/app/data/output.json`. It prints a summary of included/excluded entities
for verification.
