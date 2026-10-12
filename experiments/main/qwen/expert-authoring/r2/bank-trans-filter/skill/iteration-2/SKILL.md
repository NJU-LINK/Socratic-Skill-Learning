---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to keep only rows belonging to a target company
  whose identity must be inferred through entity resolution. Handles name
  variants (abbreviations, punctuation drift, legal-suffix changes, typos),
  and distractor entities with overlapping names. Uses evidence propagation:
  once a company alias establishes an account as belonging to the target,
  other rows on that exact account may then be included even if their alias
  is shorter. Never merges accounts by edit distance.
---

# Bank Transaction Filter — Entity Resolution Skill

## Problem

Given a CSV of bank transactions and a target company name, extract every
transaction that belongs to that company. The target company appears under
multiple name variants (abbreviations, punctuation drift, legal-suffix
changes). Other companies may have names that partially overlap the target
(subsidiaries, partners, advisors) and must remain excluded.

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
   technology, tech, consulting, consultancy`.

> **Why strip suffixes?** "North West Capital Group" and "N.W. Capital
> Holdings" are the same entity despite different suffixes. The suffixes
> "Group" and "Holdings" are generic structural words. But "Advisors",
> "Advisory", and "Partners" also appear in this list — they are stripped
> during normalization but then checked separately in step 3.

### 3. Identify target-matching name variants

For each unique company name in the dataset, compute a **core-token overlap**
score against the target name:

```
target_core = tokens(normalize(target_name))   # e.g., {"north", "west", "capital"}
name_core   = tokens(normalize(company_name))  # after suffix removal

score = |name_core ∩ target_core| / |name_core|
```

A name is a **strong match** to the target when **both** conditions hold:

- `score >= 0.70` (at least 70 % of the name's core tokens match the target)
- The name does **not** carry a **disqualifying suffix** that signals a
  separate entity.

**Disqualifying suffixes** (applied to the *original* name, before
normalization): `Advisors`, `Advisory`, `Partners`, `Partner`.

> **Rationale:** "Northwest Capital Advisors" has 67 % core overlap and
> carries the disqualifying suffix "Advisors" → excluded. "North West Cap.
> Group" has 100 % core overlap and no disqualifying suffix → included.
> "N.W. Capital Holdings" has 71 % core overlap (SequenceMatcher ≥ 0.70)
> and no disqualifying suffix → included.

**Abbreviation handling:** Initial-style abbreviations like "N.W." expand
when punctuation is removed to "nw", which is a single token. Because
"nw" does not appear in `{"north", "west", "capital"}`, the overlap score
would be low. To handle this, add an **abbreviation expansion** step before
scoring: if a token looks like an initial (1-2 characters), try matching
it against the initials of the target name. Concretely:

- "N.W." → "nw" → compare as bigram against target initials "n" + "w"
- If the initials of the target ("n", "w", "c") are all present as
  substrings of the name's tokens, treat the overlap as high.

A simpler alternative: compute `difflib.SequenceMatcher` ratio between
the stripped names (with suffixes removed) and use a threshold of ~0.65.
This naturally handles abbreviation and spacing variants. **Use both** the
token-overlap score and the SequenceMatcher ratio, taking the maximum.

### 4. Establish target accounts (EXACT MATCH + MINIMUM EVIDENCE)

Collect the set of account numbers used by rows whose names are strong
matches to the target, but **require at least 2 strong-match rows** per
account:

```
from collections import Counter
acct_strong_count = Counter()
for row in rows:
    if is_strong_match(row["Company Name"], target_name):
        acct_strong_count[row["Account Number"]] += 1

target_accounts = { acct for acct, count in acct_strong_count.items()
                    if count >= 2 }
```

> **CRITICAL: Two requirements must BOTH hold:**
>
> 1. **Exact string match only.** Never use edit distance or fuzzy
>    matching on account numbers. The spec explicitly states: "Account
>    numbers are identifiers, not numbers: preserve them exactly and do
>    not treat one-character-near account numbers as equal."
>
> 2. **Minimum evidence threshold.** An account requires at least 2
>    rows with strong-match names to be "established". A single row,
>    even with a perfect name match, could be a data-entry error and
>    does not constitute consistent evidence of account ownership.
>    This prevents a typo'd account (e.g., `BUS-41877` differing by
>    one digit from `BUS-41777`) from being incorrectly included.

### 5. Include rows (ACCOUNT GATE + NAME CHECK)

Every row is evaluated against the established target accounts:

1. **Account gate:** The row's account number must be in the
   `target_accounts` set. Rows on non-established accounts are
   excluded — even if the name is a strong match. This is the
   primary filter.
2. **Name check (for rows on established accounts):**
   - If the name is a strong match → include.
   - If the name is NOT strong but has ≥ 1 core token overlap with
     the target AND has no disqualifying suffix → include (propagation).
   - If the name has a disqualifying suffix → exclude.
   - If the name has zero overlap → exclude.

> **Key insight:** A strong name match alone is NOT sufficient. The
> account must also be independently established. This two-factor
> check prevents typo'd accounts from contaminating the output.

### 6. Build output and sort (unchanged)

- Collect all included rows.
- Sort by `Date` ascending (ISO date strings sort lexicographically).
- Write as a JSON array to `/app/data/output.json` with `json.dumps(...,
  indent=2, ensure_ascii=False)`.

---

## Decision Rules Summary

| Condition | Action |
|---|---|
| Account NOT in established target set | **Exclude** (even if name is strong match) |
| Account in target set AND name is strong match (≥ 0.70, no disq. suffix) | **Include** |
| Account in target set AND name has ≥ 1 core token overlap AND no disq. suffix | **Include** (propagation) |
| Account in target set AND name has disqualifying suffix | **Exclude** |
| Account in target set AND name has 0 overlap with target | **Exclude** |
| Account differs by even 1 char from all target accounts | **Exclude** |

---

## What NOT to Do

1. **Never use edit distance on account numbers.** Near-miss accounts are
   different accounts. `BUS-41777` and `BUS-41877` are distinct even
   though they differ by one digit.
2. **Never propagate identity to "close" accounts.** Only exact account
   string matches count.
3. **Never include a row solely because its name is a strong match.**
   The account must ALSO be an established target account. A strong
   name match on a non-established account is not enough.
4. **Never establish an account from a single row.** An account requires
   at least 2 rows with strong-match names. A single row could be a
   data-entry error (e.g., a typo'd account number).
5. **Never strip disqualifying suffixes for the disqualification check.**
   The check must be done on the original company name before any
   normalization.

---

## Self-Verification Checklist

After producing the output, verify:

1. **Account gate:** Every output row's account number is in the
   established target-account set (≥ 2 strong-match rows, exact
   string equality only).
2. **No single-row accounts:** No account appears in the output that
   has fewer than 2 strong-name-match rows in the input CSV.
3. **No distractors:** No output row has a company name ending in
   "Advisor", "Advisory", "Partner", or "Partners".
4. **No near-miss accounts:** Every account number in the output appears
   verbatim in the target-account set — no fuzzy matches.
5. **Sorted order:** Output dates are non-decreasing.
6. **Exact values:** Every field in every output object is an exact
   string copy of the corresponding CSV cell.
7. **Row count sanity:** The number of output rows equals the sum of
   all rows on established target accounts that pass the name check.

---

## Execution

Run the solution script:

```bash
python3 /path/to/skill/bank-trans-filter/scripts/solve.py
```

The script reads from `/app/data/bank_transactions.csv` and writes to
`/app/data/output.json`. It prints a summary of included/excluded entities
for verification.
