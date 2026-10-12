---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a target
  company whose identity must be resolved across spelling, punctuation,
  abbreviation, and legal-suffix variations in company names, while excluding
  separately named entities (advisors, partners, subsidiaries) and handling
  noisy account-number identifiers with near-miss distractor detection.
---

# Bank Transaction Entity-Resolution Filter

## Task Family

You receive a CSV of bank transactions at `/app/data/bank_transactions.csv` and
an instruction naming a target company.  The goal is to output every transaction
that belongs to that company to `/app/data/output.json` as a sorted JSON array,
excluding rows that belong to other entities even when their names superficially
overlap the target.

## Core Challenges (Variation Dimensions)

### 1. Company Identity Signal Variation
The target company appears under multiple name forms.  Variations include:
- **Punctuation**: `N.W. Capital` vs `North West Capital` (periods, commas stripped)
- **Abbreviation**: `North West Cap. Group` (Capital → Cap.)
- **Legal-suffix changes**: `Holdings` vs `Group` vs `Hldgs` vs bare name
- **Directional compounds**: `Northwest` (one word) vs `North West` (two words)
- **Spelling drift / typos**: character substitutions, transpositions, missing letters
- **Initialisms**: single letters standing for directional words (`N`, `W`)

### 2. Transaction Membership Inference
- A company may use **multiple account numbers** (different legitimate accounts).
- A recognizable alias on one row **establishes** its account as belonging to
  the target; other rows on that established account are included even with shorter aliases.
- Evidence must be **propagated**: newly included rows may establish additional
  accounts, which in turn surface more rows.

### 3. Distractor Entity Confusability
- Non-target companies may share some name tokens with the target.
- **Entity-type suffixes** (Advisors, Advisory, Partners, Consulting) signal
  separate entities that must be excluded even when core tokens match.
- **Near-miss account numbers** (differing by 1–2 characters from a legitimate
  target account) are distractors: the row must be excluded even if the company
  name is a valid alias.  This catches planted data-entry errors where a
  legitimate-looking name is paired with a corrupted account number.
- A row can still be included by its **name** only when the account number is
  either already established or not a near-miss of any established account.

## Strategy

### Decision Rules

| Signal | Rule |
|--------|------|
| Company name core tokens fully match target core tokens | **Include** (unless entity suffix present) |
| Company name has entity-type suffix (Advisors, Partners, Advisory, …) | **Exclude** even if core tokens match |
| Row is on an established target account AND name partially matches target | **Include** (propagation) |
| Account number differs by ≤ 2 chars from an established target account | **Near-miss distractor** — exclude the account and its rows |
| Company name has no token overlap with target | **Exclude** regardless of account |

### Suffix Taxonomy

**Generic suffixes** (may vary freely within the same entity — strip before comparison):
`Group`, `Holdings/Hldgs`, `Inc`, `LLC`, `Corp`, `Ltd`, `Co/Company`,
`Corporation`, `Limited`, `PLC`, `LLP`, `Trust`, `Fund`, `Bank`, `Financial`,
`International/Intl`, `Technologies/Tech`, `Solutions`, `Systems`, `Industries`,
`Services`

**Entity suffixes** (signal a separate entity — exclude):
`Advisors`, `Advisory`, `Partners`, `Consulting`, `Consultancy`, `Management`,
`Wealth`, `Research`, `Labs`, `Laboratories`, `Institute`, `Foundation`

### Near-Miss Account Detection

After establishing candidate accounts from alias-matched rows, perform pairwise
edit-distance (Levenshtein) comparison.  For any pair within distance ≤ 2:

1. Count the number of alias-matched rows on each account.
2. The account with **more rows** is the legitimate account.
3. The account with **fewer rows** is a near-miss distractor — remove it.
4. Ties are broken deterministically (lexicographic order).

This filter is applied **before** the propagation loop and **during** it: any
newly discovered account is also checked against existing established accounts
before being added.

Example: `BUS-41777` (5 rows) vs `BUS-41877` (1 row) → distance = 1 →
`BUS-41877` is removed as a distractor.

## Procedure

### Step 1 — Identify the target name

Read the task instruction (usually in the prompt) to extract the target company
name.  Example: *"Keep only the transactions that belong to North West Capital"*
→ target = `North West Capital`.

### Step 2 — Run the filter script

```bash
python3 scripts/filter_transactions.py "TARGET NAME"
```

The script implements a 5-phase pipeline:

1. **Phase 1 — Alias discovery**: scores every unique company name for token
   overlap with target core tokens; names with full overlap and no entity suffix
   become target aliases.
2. **Phase 2 — Account establishment + near-miss filtering**: collects all
   account numbers from alias-matched rows, then removes accounts that are
   near-misses (edit distance ≤ 2) of more-frequent accounts.
3. **Phase 3 — Propagation loop**: finds rows on established accounts whose
   names partially match the target (≥ 50 % core-token overlap, no entity
   suffix), adds them, and re-checks for new accounts (also subject to
   near-miss filtering) until stable.
4. **Phase 4 — Collection**: gathers all rows where the name is an included
   alias **and** the account is an established account (excluding any rows
   on near-miss distractor accounts even if the name matched).
5. **Output**: sorts by `Date` ascending, writes `/app/data/output.json`.

### Step 3 — Verify the output

Run these checks after the script finishes:

```python
import json

with open("/app/data/output.json") as f:
    data = json.load(f)

# 1. Valid JSON array
assert isinstance(data, list), "Output must be a JSON array"

# 2. Each row has exactly the 6 required keys
required = {"Company Name", "Account Number", "Date",
            "Amount", "Transaction Type", "Description"}
for row in data:
    assert set(row.keys()) == required, f"Bad keys: {row.keys()}"

# 3. All values are strings
for row in data:
    for k, v in row.items():
        assert isinstance(v, str), f"Non-string value: {k}={v!r}"

# 4. Sorted by Date ascending
dates = [r["Date"] for r in data]
assert dates == sorted(dates), "Dates not sorted ascending"

# 5. No excluded entity-type names leaked in
for row in data:
    name_lower = row["Company Name"].lower()
    for suffix in ["advisors", "advisory", "partners"]:
        assert suffix not in name_lower, f"Excluded entity found: {row['Company Name']}"

# 6. No near-miss account distractors
#    Check that no two accounts in the output are within edit distance 2
#    unless both have many rows (legitimate multi-account entity).
accounts = list({r["Account Number"] for r in data})
for i in range(len(accounts)):
    for j in range(i+1, len(accounts)):
        a, b = accounts[i], accounts[j]
        dist = sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))
        if dist <= 2:
            print(f"WARNING: Near-miss accounts in output: {a} vs {b}")
```

## Manual Override

If the script is unavailable or the data exhibits unusual patterns (e.g.,
severe spelling drift not caught by abbreviation expansion), fall back to a
manual workflow:

1. List all unique company names: `cut -d',' -f1 file.csv | sort -u`
2. Identify target aliases by visual inspection (look for punctuation variants,
   abbreviations, legal-suffix changes of the target name).
3. Collect account numbers from alias-matched rows.
4. **Check for near-miss accounts**: compare each pair of candidate accounts
   character-by-character.  If two accounts differ by only 1–2 characters, the
   one with fewer rows is a distractor — exclude it.
5. Check all rows on surviving accounts for additional matches.
6. Exclude any name with an entity-type suffix.
7. Build the JSON output with the 6 required keys, sorted by Date.

## Edge Cases

- **Empty result**: If no company names match the target core tokens, output `[]`.
- **Single-token target**: If the target name has only one core token (e.g.,
  "Momentum"), require exact token match — do not propagate on partial overlap.
- **Account-only evidence**: A row whose name has zero overlap with the target
  should **not** be included just because it shares an account with the target.
  Name evidence is always required.
- **Near-miss account with valid name**: Even when a company name is a valid
  target alias, the row is excluded if its account number is a near-miss of a
  more-frequent established account.  The account-level distractor signal
  overrides the name-level match.
- **Preserve values exactly**: Amount strings like `"-$197887.00"` must keep
  their original formatting including the dollar sign and leading minus.
- **Multiple legitimate accounts**: If two accounts differ by more than 2
  characters, both may be legitimate (e.g., `BUS-30001` and `BUS-41777` have
  edit distance 5 — clearly different accounts).
