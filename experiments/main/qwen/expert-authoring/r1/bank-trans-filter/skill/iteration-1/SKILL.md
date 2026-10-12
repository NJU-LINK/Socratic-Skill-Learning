---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a target
  company whose identity must be resolved across spelling, punctuation,
  abbreviation, and legal-suffix variations in company names, while excluding
  separately named entities (advisors, partners, subsidiaries) and handling
  noisy account-number identifiers.
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
  the target; other rows on that account are included even with shorter aliases.
- Evidence must be **propagated**: newly included rows may establish additional
  accounts, which in turn surface more rows.

### 3. Distractor Entity Confusability
- Non-target companies may share some name tokens with the target.
- **Entity-type suffixes** (Advisors, Advisory, Partners, Consulting) signal
  separate entities that must be excluded even when core tokens match.
- Account numbers that differ by one character from a target account are **not**
  the same account; do not merge on account similarity alone.
- A row can still be included by its **name** even if its account number looks
  like a typo of an established target account — the name match is independent
  evidence.

## Strategy

### Decision Rules

| Signal | Rule |
|--------|------|
| Company name core tokens fully match target core tokens | **Include** (unless entity suffix present) |
| Company name has entity-type suffix (Advisors, Partners, Advisory, …) | **Exclude** even if core tokens match |
| Row is on an established target account AND name partially matches target | **Include** (propagation) |
| Account number differs by 1 char from established target account | **Do NOT merge** accounts; evaluate the row on its name independently |
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

## Procedure

### Step 1 — Identify the target name

Read the task instruction (usually in the prompt) to extract the target company
name.  Example: *"Keep only the transactions that belong to North West Capital"*
→ target = `North West Capital`.

### Step 2 — Run the filter script

```bash
python3 scripts/filter_transactions.py "TARGET NAME"
```

The script:
1. Reads `/app/data/bank_transactions.csv`.
2. Computes **core identity tokens** for the target (lowercase, strip
   punctuation, expand abbreviations, remove generic suffixes).
3. **Phase 1 — Alias discovery**: scores every unique company name for token
   overlap with target core tokens; names with full overlap and no entity suffix
   become target aliases.
4. **Phase 2 — Account establishment**: collects all account numbers used by
   alias-matched rows.
5. **Phase 3 — Propagation loop**: finds rows on established accounts whose
   names partially match the target (≥ 50 % core-token overlap, no entity
   suffix), adds them, and re-checks for new accounts until stable.
6. **Phase 4 — Collection**: gathers all included rows, sorts by `Date`
   ascending, and writes `/app/data/output.json`.

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
```

## Manual Override

If the script is unavailable or the data exhibits unusual patterns (e.g.,
severe spelling drift not caught by abbreviation expansion), fall back to a
manual workflow:

1. List all unique company names: `cut -d',' -f1 file.csv | sort -u`
2. Identify target aliases by visual inspection (look for punctuation variants,
   abbreviations, legal-suffix changes of the target name).
3. Collect account numbers from alias-matched rows.
4. Check all rows on those accounts for additional matches.
5. Exclude any name with an entity-type suffix.
6. Build the JSON output with the 6 required keys, sorted by Date.

## Edge Cases

- **Empty result**: If no company names match the target core tokens, output `[]`.
- **Single-token target**: If the target name has only one core token (e.g.,
  "Momentum"), require exact token match — do not propagate on partial overlap.
- **Account-only evidence**: A row whose name has zero overlap with the target
  should **not** be included just because it shares an account with the target.
  Name evidence is always required.
- **Preserve values exactly**: Amount strings like `"-$197887.00"` must keep
  their original formatting including the dollar sign and leading minus.
