---
name: bank-trans-filter
description: >
  Extract bank transactions belonging to a target company from a CSV file
  using fuzzy entity resolution with evidence propagation. Handles company
  name variations (abbreviation, punctuation, spelling, legal-suffix changes),
  multi-account entities, and exclusion of separately-named entities
  (Advisors, Partners) that share superficial naming overlap.
---

# Bank Transaction Entity Resolution Filter

## Task Overview

You are given bank transactions in a CSV file at `/app/data/bank_transactions.csv`.
Your job is to keep only transactions belonging to a specified target company,
then write the result as a JSON array to `/app/data/output.json`.

The hard part is **entity resolution**: the same company appears under many name
variants (typos, abbreviations, punctuation changes, legal-suffix differences),
and separately-named entities (Advisors, Partners) may share naming overlap but
must remain excluded.

## Decision Rules

### 1. Parse the Target

Extract the target company name from the task instruction (e.g. "North West Capital").
This is the canonical reference you will resolve against.

### 2. Normalise Company Names

For every company name in the dataset (and the target), produce a normalised form:

1. **Lowercase** the string.
2. **Expand known abbreviations** using word-boundary replacement:
   - `N.W.` / `N.W` / `NW.` / `NW` → `north west`
   - `Cap.` / `Cap` → `capital`
   - `Intl.` → `international`, `Mfg.` → `manufacturing`, `Svcs.` → `services`, etc.
   - Build a reasonable abbreviation table; add domain-specific ones as needed.
3. **Strip punctuation** (replace non-alphanumeric characters with spaces).
4. **Collapse whitespace** and trim.

### 3. Separate Core Words from Suffixes

Split the normalised name into **core identifying words** and **trailing suffixes**:

| Category | Examples | Effect on matching |
|---|---|---|
| **Legal / entity suffixes** | Group, Holdings, Hldgs, Ltd, Inc, Corp, LLC, Co, Company, PLC | Ignored during core matching (they vary freely for the same entity) |
| **Separate-business indicators** | Advisors, Advisory, Partners, Consulting, Consultancy, Associates, Ventures, Fund, Management | Flags the name as a **different entity** that must be excluded |
| **Core words** | Everything else (e.g. `north west capital`) | Used for identity matching |

### 4. Identify Confirmed Aliases

A company name is a **confirmed alias** of the target if **both** conditions hold:

- **Core match**: The core words (after normalisation and suffix stripping) have
  high token overlap with the target core. Use Jaccard similarity ≥ 0.6 **or**
  substring containment (one core is contained in the other).
- **No separate-business indicator**: The normalised name does not contain any
  word from the separate-business set.

> **Why this works**: "North West Capital Group" and "N.W. Capital Holdings"
> both reduce to the core `north west capital` with only legal suffixes → confirmed.
> "North West Capital Advisors" has core `north west capital` but carries
> "advisors" → excluded. "Northwest Capital Partners" has a similar core but
> carries "partners" → excluded.

### 5. Establish Target Accounts

Collect every account number that appears on at least one row whose company name
is a confirmed alias. These are the **established target accounts**.

> **Evidence propagation**: A short or ambiguous alias (e.g. "N.W. Capital Hldgs")
> on the same account as a clearer alias (e.g. "N.W. Capital Holdings") is
> automatically included because the account was established by the clearer alias.

### 6. Collect Matching Rows

Include every row whose account number is in the established-account set,
regardless of the company name on that specific row. This handles cases where
an account has rows with shorter or more corrupted aliases.

### 7. Format Output

- JSON array (no top-level wrapper) written to `/app/data/output.json`.
- One object per matched row with the exact CSV column keys:
  `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`.
- **All values are strings** preserved exactly from the CSV (do not convert
  Amount to a number; do not strip `$` or `-` signs).
- **Sorted by `Date` ascending** (stable sort; preserve original order for ties).
- **Account numbers are identifiers**: never treat two account numbers as equal
  just because they differ by one character. Each distinct string is a distinct
  account.

## Implementation Strategy

Write a self-contained Python script (no external dependencies beyond stdlib):

```
1. Read CSV with csv.DictReader
2. Normalise every unique company name
3. Identify confirmed aliases (core match + no separate-business flag)
4. Collect established accounts from alias rows
5. Filter rows by account membership
6. Sort by Date
7. Write JSON with json.dump
```

Key implementation details:
- Use `csv.DictReader` to preserve exact string values (no type coercion).
- Use `re.sub(r'\b' + re.escape(abbr) + r'\b', full, lower)` for
  abbreviation expansion to avoid partial-word matches.
- Sort abbreviation replacements by descending length so longer patterns
  match first (e.g. `n.w.` before `nw`).
- The Jaccard similarity threshold of 0.6 handles moderate word drift;
  the substring-containment fallback handles cases where the core is very short.

## Variation Dimensions to Handle

### Company Identity Signal Variation
- Punctuation: `N.W.` vs `NW` vs `North West`
- Abbreviation: `Cap.` for `Capital`, `Hldgs` for `Holdings`
- Spelling typos: `Mounta5n` for `Mountain`, `Insurce` for `Insurance`
- Legal-suffix changes: `Group` vs `Holdings` vs `Ltd`
- Identifier corruption in either name or account number

### Transaction Membership Inference
- Multiple accounts per entity (a company can use several bank accounts)
- Sparse anchor rows establishing entity membership indirectly
- Propagation: a clear alias establishes an account; other rows on that
  account are included even if their own alias is less clear
- Account reuse: do NOT assume two similar-looking account numbers are the same

### Distractor Entity Confusability
- Names with partial overlap: "Northern Light Energy" shares "North" but is unrelated
- Separate business suffixes: Advisors, Advisory, Partners
- Near-miss account numbers: BUS-41777 vs BUS-41877 are different accounts
- Subsidiaries or partner firms that should remain excluded

## Verification Checklist

After writing output.json, verify:
1. [ ] Output is a valid JSON array (not wrapped in an object).
2. [ ] Every record has exactly the 6 required keys.
3. [ ] All values are strings (no numbers, no nulls).
4. [ ] Records are sorted by Date ascending.
5. [ ] No transactions from excluded entities (check for Advisors/Partners names).
6. [ ] Account numbers are preserved exactly from the CSV.
7. [ ] Print a summary: number of matched rows, aliases found, accounts established.
