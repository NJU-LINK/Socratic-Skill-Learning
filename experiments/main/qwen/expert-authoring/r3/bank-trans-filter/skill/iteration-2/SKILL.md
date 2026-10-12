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

### 5. Establish Target Accounts (with confirmation threshold)

This is the critical step where evidence must be strong enough.

**Rule: an account is "established" for the target only if ≥ 2 rows on that
account carry confirmed-alias names.**

Rationale: a single occurrence of a company name on an account is fragile
evidence — it could be a data-entry error, a one-time payment to a similarly
named entity, or a corrupted alias. Multiple rows provide corroboration that
the account genuinely belongs to the target.

Algorithm:
1. Group all rows by account number.
2. For each account, count how many rows have a confirmed-alias company name.
3. An account is **established** if this count ≥ 2.

> **Example**: "N.W. Capital Holdings" (a confirmed alias) appears on
> BUS-41777 five times → established. The same name appears on BUS-41877
> only once → NOT established. "North West Cap. Group" / "North West Capital
> Group" appear on BUS-30001 eight times → established.

### 6. Collect Matching Rows (with explicit exclusion)

Include every row whose account number is in the established-account set.

**But add an explicit exclusion filter**: even on established accounts, remove
any row whose company name contains a separate-business indicator (Advisors,
Advisory, Partners, etc.). This prevents leakage if a separate entity happens
to share an account with the target.

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
4. Group rows by account; count confirmed-alias rows per account
5. Establish accounts where confirmed-alias count >= 2
6. Filter rows: account is established AND company name has no separate-business indicator
7. Sort by Date
8. Write JSON with json.dump
```

Key implementation details:
- Use `csv.DictReader` to preserve exact string values (no type coercion).
- Use `re.sub(r'\b' + re.escape(abbr) + r'\b', full, lower)` for
  abbreviation expansion to avoid partial-word matches.
- Sort abbreviation replacements by descending length so longer patterns
  match first (e.g. `n.w.` before `nw`).
- The Jaccard similarity threshold of 0.6 handles moderate word drift;
  the substring-containment fallback handles cases where the core is very short.

### Complete reference implementation

```python
import csv, json, re
from collections import defaultdict

# --- Configuration ---
SEPARATE_BUSINESS_WORDS = {
    "advisors", "advisory", "partners", "consulting", "consultancy",
    "associates", "ventures", "fund", "management",
}
LEGAL_SUFFIXES = {
    "group", "holdings", "hldgs", "ltd", "limited", "inc", "incorporated",
    "corp", "corporation", "llc", "co", "company", "plc", "lp", "llp",
    "pty", "gmbh", "ag", "sa", "bv", "nv",
}
ABBREVIATION_MAP = {
    "n.w.": "north west", "n.w": "north west", "nw.": "north west", "nw": "north west",
    "cap.": "capital", "cap": "capital",
    "intl.": "international", "intl": "international",
    "mfg.": "manufacturing", "mfg": "manufacturing",
    "svcs.": "services", "svcs": "services",
    "sys.": "systems", "sys": "systems",
}
MIN_ROWS_TO_ESTABLISH = 2  # Minimum confirmed-alias rows on an account

def expand_abbreviations(name):
    lower = name.lower()
    for abbr, full in sorted(ABBREVIATION_MAP.items(), key=lambda x: -len(x[0])):
        lower = re.sub(r'\b' + re.escape(abbr) + r'\b', full, lower)
    return lower

def normalise_company_name(name):
    n = name.lower().strip()
    n = expand_abbreviations(n)
    n = re.sub(r"[^a-z0-9\s-]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n

def extract_core_words(normalised):
    tokens = normalised.split()
    core = [t for t in tokens if t not in LEGAL_SUFFIXES and t not in SEPARATE_BUSINESS_WORDS]
    return " ".join(core)

def has_separate_business_indicator(name):
    tokens = normalise_company_name(name).split()
    return any(t in SEPARATE_BUSINESS_WORDS for t in tokens)

def jaccard_similarity(a, b):
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def is_core_match(name_norm, target_core, threshold=0.6):
    name_core = extract_core_words(name_norm)
    if jaccard_similarity(name_core, target_core) >= threshold:
        return True
    if target_core in name_core or name_core in target_core:
        return True
    return False

def resolve(rows, target_company):
    target_core = extract_core_words(normalise_company_name(target_company))

    # Step 1: confirmed aliases
    unique_names = set(r["Company Name"] for r in rows)
    confirmed = set()
    for name in unique_names:
        norm = normalise_company_name(name)
        if is_core_match(norm, target_core) and not has_separate_business_indicator(name):
            confirmed.add(name)

    # Step 2: establish accounts (>= MIN_ROWS_TO_ESTABLISH confirmed-alias rows)
    acct_confirmed_count = defaultdict(int)
    for r in rows:
        if r["Company Name"] in confirmed:
            acct_confirmed_count[r["Account Number"]] += 1

    established = {acct for acct, cnt in acct_confirmed_count.items()
                   if cnt >= MIN_ROWS_TO_ESTABLISH}

    # Step 3: collect rows (established account + no separate-business name)
    result = []
    for r in rows:
        if r["Account Number"] in established:
            if not has_separate_business_indicator(r["Company Name"]):
                result.append(r)

    result.sort(key=lambda r: r["Date"])
    return result, confirmed, established
```

## Variation Dimensions to Handle

### Company Identity Signal Variation
- Punctuation: `N.W.` vs `NW` vs `North West`
- Abbreviation: `Cap.` for `Capital`, `Hldgs` for `Holdings`
- Spelling typos: `Mounta5n` for `Mountain`, `Insurce` for `Insurance`
- Legal-suffix changes: `Group` vs `Holdings` vs `Ltd`
- Identifier corruption in either name or account number

### Transaction Membership Inference
- Multiple accounts per entity (a company can use several bank accounts)
- **Confirmation threshold**: require ≥ 2 rows with confirmed aliases on an
  account before establishing it. This protects against single-occurrence
  false positives where a similarly-named entity happens to appear once.
- Propagation: once an account is established, ALL rows on it are included
  (even rows with shorter/corrupted aliases), subject to explicit exclusion.
- Account reuse: do NOT assume two similar-looking account numbers are the same

### Distractor Entity Confusability
- Names with partial overlap: "Northern Light Energy" shares "North" but is unrelated
- Separate business suffixes: Advisors, Advisory, Partners
- Near-miss account numbers: BUS-41777 vs BUS-41877 are different accounts
- Subsidiaries or partner firms that should remain excluded
- **Explicit post-filter**: even on established accounts, exclude any row whose
  company name carries a separate-business indicator

## Verification Checklist

After writing output.json, verify:
1. [ ] Output is a valid JSON array (not wrapped in an object).
2. [ ] Every record has exactly the 6 required keys.
3. [ ] All values are strings (no numbers, no nulls).
4. [ ] Records are sorted by Date ascending.
5. [ ] No transactions from excluded entities (Advisors/Advisory/Partners names).
6. [ ] Account numbers are preserved exactly from the CSV.
7. [ ] Print a summary: number of matched rows, aliases found, accounts established,
      and the confirmed-alias count per account (to verify the threshold).
8. [ ] Every established account has ≥ 2 rows with confirmed-alias names.
