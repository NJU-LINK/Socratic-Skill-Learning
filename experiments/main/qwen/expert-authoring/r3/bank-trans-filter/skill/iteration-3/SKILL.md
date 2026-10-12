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

For every company name in the dataset (and the target), produce a normalised form.
**Order matters — follow these steps exactly:**

1. **Lowercase** the string.
2. **Strip all periods** (replace `.` with empty string). This normalises
   `N.W.` → `NW`, `N. W.` → `N W`, `Cap.` → `Cap` BEFORE abbreviation lookup.
3. **Expand known abbreviations** using word-boundary regex replacement (longest-first):
   - `n w` / `nw` → `north west`
   - `cap` → `capital`
   - `intl` → `international`, `mfg` → `manufacturing`, `svcs` → `services`, etc.
   - Build a reasonable abbreviation table; add domain-specific ones as needed.
4. **Strip remaining punctuation** (replace non-alphanumeric characters with spaces).
5. **Collapse whitespace** and trim.

> **Why strip periods first**: `N. W. Capital Holdings` would otherwise
> normalise to `n w capital holdings` (periods become spaces, leaving bare
> letters). By stripping periods first, `N. W.` becomes `N W` which the
> abbreviation expander correctly maps to `north west`.

### 3. Separate Core Words from Suffixes

Split the normalised name into **core identifying words** and **trailing suffixes**:

| Category | Examples | Effect on matching |
|---|---|---|
| **Legal / entity suffixes** | Group, Holdings, Hldgs, Ltd, Inc, Corp, LLC, Co, Company, PLC | Ignored during core matching (they vary freely for the same entity) |
| **Separate-business indicators** | Advisors, Advisory, Partners, Consulting, Consultancy, Associates, Ventures, Fund, Management | Flags the name as a **different entity** that must be excluded |
| **Core words** | Everything else (e.g. `north west capital`) | Used for identity matching |

### 4. Identify Confirmed Aliases

A company name is a **confirmed alias** of the target if **both** conditions hold:

- **Core match**: The core words match the target core via the 4-level
  Matching Cascade (see below).
- **No separate-business indicator**: The normalised name does not contain any
  word from the separate-business set.

> **Why this works**: "North West Capital Group" and "N.W. Capital Holdings"
> both reduce to the core `north west capital` with only legal suffixes → confirmed.
> "North West Capital Advisors" has core `north west capital` but carries
> "advisors" → excluded. "Northwest Capital Partners" has a similar core but
> carries "partners" → excluded.

### 5. Establish Target Accounts (with confirmation threshold)

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

### 6. Collect Matching Rows (with explicit exclusion)

Include every row whose account number is in the established-account set.

**Explicit exclusion filter**: even on established accounts, remove any row
whose company name contains a separate-business indicator (Advisors, Advisory,
Partners, etc.). This prevents leakage if a separate entity shares an account.

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

## Matching Cascade

The core-match check uses a **4-level cascade**, tried in order. A match at
any level succeeds:

### Level 1 — Token Jaccard ≥ 0.6
Standard word-set overlap. Works for clean names with only suffix differences.

### Level 2 — Substring Containment
One core is a substring of the other. Handles cases where the alias drops or
adds core words (e.g. `north west` is contained in `north west capital`).

### Level 3 — Compound-Word Resolution
If a candidate token is the concatenation of two target-core words, split it
and re-check. Example: `northwest capital` → resolve `northwest` to
`north west` → `north west capital` → exact match.

Algorithm: for each token in the candidate core, try splitting it into 2 or 3
parts where every part is a word in the target core. If any split succeeds,
re-run Level 1 and Level 2 on the resolved core.

### Level 4 — Word-Level Fuzzy Match (Edit Distance)
Align the candidate and target cores word-by-word (requires **same word
count**). For each word pair, compute Levenshtein edit distance. If every
pair has `distance / max(len_a, len_b) ≤ 0.45`, it is a match.

Example: `nrth wst captal` vs `north west capital`:
- `nrth` → `north` (dist=1, ratio=0.20) ✓
- `wst` → `west` (dist=1, ratio=0.25) ✓
- `captal` → `capital` (dist=1, ratio=0.14) ✓ → **MATCH**

Example: `north west cptl` vs `north west capital`:
- `north` → `north` (dist=0) ✓
- `west` → `west` (dist=0) ✓
- `cptl` → `capital` (dist=3, ratio=0.43) ✓ → **MATCH**

The same-word-count requirement prevents false matches where one name has
extra or missing words. The 0.45 threshold handles severe consonant-only
abbreviations (like `cptl` for `capital`) while still rejecting unrelated
words (e.g. `momentum` vs `north` has ratio 0.88).

**Separate-business filter runs BEFORE the cascade**: if a name contains
Advisors/Partners/etc., it is excluded without checking the cascade.

## Complete Reference Implementation

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
# Abbreviation map (period-free forms; periods are stripped before lookup)
ABBREVIATION_MAP = {
    "n w": "north west", "nw": "north west",
    "cap": "capital",
    "intl": "international",
    "mfg": "manufacturing",
    "svcs": "services",
    "sys": "systems",
    # With-period fallback forms (in case of partial stripping)
    "n.w.": "north west", "n. w.": "north west",
    "n.w": "north west", "nw.": "north west",
    "cap.": "capital", "intl.": "international",
    "mfg.": "manufacturing", "svcs.": "services", "sys.": "systems",
}
MIN_ROWS_TO_ESTABLISH = 2

# --- Normalisation ---
def normalise_company_name(name):
    n = name.lower().strip()
    n = n.replace('.', '')                            # strip periods FIRST
    for abbr, full in sorted(ABBREVIATION_MAP.items(),
                             key=lambda x: -len(x[0])):
        n = re.sub(r'\b' + re.escape(abbr) + r'\b', full, n)
    n = re.sub(r"[^a-z0-9\s-]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n

def extract_core_words(normalised):
    tokens = normalised.split()
    core = [t for t in tokens
            if t not in LEGAL_SUFFIXES and t not in SEPARATE_BUSINESS_WORDS]
    return " ".join(core)

def has_separate_business_indicator(name):
    tokens = normalise_company_name(name).split()
    return any(t in SEPARATE_BUSINESS_WORDS for t in tokens)

# --- Matching cascade ---
def levenshtein(a, b):
    if len(a) < len(b): return levenshtein(b, a)
    if len(b) == 0: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]

def try_split_compound(token, dict_words):
    for i in range(1, len(token)):
        left, right = token[:i], token[i:]
        if left in dict_words and right in dict_words:
            return left + " " + right
        for j in range(i + 1, len(token)):
            mid, right2 = token[i:j], token[j:]
            if (left in dict_words and mid in dict_words
                    and right2 in dict_words):
                return left + " " + mid + " " + right2
    return token

def resolve_compounds(candidate_core, target_core):
    dict_words = set(target_core.split())
    return " ".join(
        try_split_compound(t, dict_words) for t in candidate_core.split()
    )

def word_fuzzy_match(core_a, core_b, max_edit_ratio=0.45):
    wa, wb = core_a.split(), core_b.split()
    if len(wa) != len(wb):
        return False
    for a, b in zip(wa, wb):
        if levenshtein(a, b) / max(len(a), len(b), 1) > max_edit_ratio:
            return False
    return True

def is_core_match(name_core, target_core, threshold=0.6):
    # Level 1: Token Jaccard
    sa, sb = set(name_core.split()), set(target_core.split())
    if sa and sb and len(sa & sb) / len(sa | sb) >= threshold:
        return True
    # Level 2: Substring containment
    if target_core in name_core or name_core in target_core:
        return True
    # Level 3: Compound-word resolution
    resolved = resolve_compounds(name_core, target_core)
    if resolved != name_core:
        sa2, sb2 = set(resolved.split()), set(target_core.split())
        if sa2 and sb2 and len(sa2 & sb2) / len(sa2 | sb2) >= threshold:
            return True
        if target_core in resolved or resolved in target_core:
            return True
    # Level 4: Word-level fuzzy match (edit distance)
    if word_fuzzy_match(name_core, target_core, max_edit_ratio=0.45):
        return True
    if (resolved != name_core
            and word_fuzzy_match(resolved, target_core, max_edit_ratio=0.45)):
        return True
    return False

# --- Main pipeline ---
def resolve(rows, target_company):
    target_core = extract_core_words(normalise_company_name(target_company))

    # Step 1: confirmed aliases
    unique_names = set(r["Company Name"] for r in rows)
    confirmed = set()
    for name in unique_names:
        if has_separate_business_indicator(name):
            continue
        norm = normalise_company_name(name)
        core = extract_core_words(norm)
        if is_core_match(core, target_core):
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
    return result, confirmed, established, acct_confirmed_count
```

## Variation Dimensions to Handle

### Company Identity Signal Variation
- Punctuation: `N.W.` vs `N. W.` vs `NW` vs `North West`
- Abbreviation: `Cap.` for `Capital`, `Hldgs` for `Holdings`, `Cptl` for `Capital`
- Compound words: `NorthWest` (no space) vs `North West` (space)
- Spelling typos: `Mounta5n` for `Mountain`, `Insurce` for `Insurance`
- Severe drift: `Nrth Wst Captal` for `North West Capital`
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
7. [ ] Print a diagnostic summary showing:
       - Confirmed aliases found and their normalised cores
       - Per-account confirmed-alias counts (to verify the threshold)
       - Established vs rejected accounts
       - Total matched rows
8. [ ] Every established account has ≥ 2 rows with confirmed-alias names.
9. [ ] Cross-check: manually inspect the first few and last few rows of the
       output to catch any unexpected inclusions.
