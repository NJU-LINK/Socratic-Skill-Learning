---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a specified
  target company, handling noisy company-name variants (abbreviations, typos,
  legal-suffix changes, partial names, initials), evidence propagation from
  company-name aliases to account numbers, and exclusion of confusable
  distractor entities (advisors, partners, subsidiaries, near-miss names).
  Outputs a JSON array sorted by date with all values preserved as strings.
---

# Bank Transaction Filter

## Overview

Given a CSV of bank transactions and a target company name (from the task
instruction), extract all rows belonging to that company. The challenge is that
the same company appears under multiple name variants and account numbers,
while confusable entities (advisors, partners, subsidiaries, companies with
similar names) must be excluded.

## General Algorithm

### Step 1: Parse and Understand the Data

Read the CSV file. Identify the column names (typically: `Company Name`,
`Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`).
Catalogue all unique company names and account numbers in the file.

### Step 2: Identify the Target Company Name

Extract the target company name from the task instruction. This is the
"canonical" name to match against.

### Step 3: Multi-Pass Entity Resolution

#### Pass 1 — Anchor Discovery (Name-Based Matching)

Identify "anchor" rows whose company name is a clear variant of the target.
Apply these matching rules:

**Normalization pipeline:**
1. Lowercase the name
2. Replace punctuation (periods, commas, hyphens) with spaces
3. Collapse multiple spaces
4. Expand compound direction words: `northwest` → `north west`, etc.

**Matching strategies (any one is sufficient):**

1. **Exact match** after normalization.

2. **Core-word match** after:
   - Expanding abbreviations (`Cap.` → `Capital`, `Hldgs` → `Holdings`,
     `Co` → `Company`, `Corp` → `Corporation`, `Ltd` → `Limited`, etc.)
   - Stripping legal suffixes (`Group`, `Holdings`, `LLC`, `Inc`, `Corp`,
     `Ltd`, `Co`, etc.)
   - Comparing the remaining core words for equality or prefix containment.

3. **Initials match**: When the first K words of a company name are single
   letters matching the first letters of the first K target words, and the
   remaining words match the remaining target words.
   - Example: `N.W. Capital Holdings` → initials `N`, `W` match `North`,
     `West`; remaining `Capital` matches after stripping `Holdings`.

4. **Fuzzy match** (SequenceMatcher ratio ≥ 0.85) for typo variants.

**Critical exclusion — separate entity detection:**

A company name that adds a distinct business designation to the target's core
name is a **separate legal entity**, NOT the target. These designations include:
`Advisors`, `Advisory`, `Partners`, `Associates`, `Consulting`, `Management`,
`Brokerage`, `Ventures`.

Example: `North West Capital Advisors` is separate from `North West Capital`.

**However**, this is a NAME-ONLY signal. In Pass 2, account evidence can
override this exclusion (see Pass 2 below).

#### Pass 1.5 — Near-Miss Account Filtering

After identifying candidate accounts from name-matched rows, check whether any
candidate account is a **near-miss** (1-2 character edit distance) of another
candidate account that has stronger evidence (multiple anchor rows).

**Why this matters:** Account numbers are identifiers, not numbers. The spec
explicitly states: *"do not treat one-character-near account numbers as equal."*
When a name-matched row proposes a new account that differs by only 1-2
characters from an already-established target account, it is likely a **typo**
in the account number, not a separate legitimate account. Including it would
violate the exact-identifier rule.

**Algorithm:**
1. Count anchor rows per candidate account.
2. Accounts with **≥2 anchor rows** are strongly established.
3. For accounts with only 1 anchor row: if the account number is within edit
   distance 2 of a strongly established account, **exclude** it (and its rows).
4. Remaining single-anchor accounts that are NOT near-misses are established.

**Example from v01:** `BUS-41877` (1 row, "N.W. Capital Holdings") differs from
established `BUS-41777` by 1 character → excluded as a near-miss account.

#### Pass 2 — Account-Based Evidence Propagation (Context-Aware)

From established accounts (after Pass 1.5 filtering), include rows that have
a plausible relationship to the target company.

**Name plausibility check:**

Not every row on an established target account belongs to the target. The spec
mentions "account reuse patterns that require caution" — a non-target company
may share an account number with the target. For each row on an established
account, check that its company name is plausibly related to the target:

1. **Name match** (via Pass 1 rules) → include
2. **Separate entity with matching core** (override) → include
3. **Shares at least one significant word** (length > 2) with the target core,
   after abbreviation expansion → include (catches shorter aliases)
4. **Fuzzy similarity ≥ 0.4** with the normalized target name → include
5. **Otherwise** → exclude (completely unrelated company on shared account)

**Context-dependent override for separate entities:**

When a row sits on an established target account AND has a separate-entity
designator in its name, the account evidence can override the name-based
exclusion. The override fires when:
1. The row is on an account established by clear name anchors (Pass 1), AND
2. The row's core name (after stripping both legal suffixes AND designator
   words) matches the target's core words.

This implements the spec's "unless the rows provide consistent evidence that
they are the target itself" clause. Being on the target's own account + having
a core name that aligns with the target = consistent evidence.

Example: If `North West Capital Advisors` appears on BUS-30001 (established by
`North West Cap. Group` rows), it IS included — the account evidence + core
name consistency together constitute the required "consistent evidence."

**Account numbers are authoritative identifiers:**

Once an account is established as belonging to the target, rows with plausible
name variants on that account are included. The account number is the primary
identifier, but rows with completely unrelated company names are still excluded
to handle account reuse patterns.

**Important rules:**
- Account numbers are **exact identifiers**. Never fuzzy-match account numbers.
  `BUS-41777` ≠ `BUS-41877` (different accounts).
- However, a row on a different account can still be included if its company
  name independently matches the target via Pass 1 rules.
- Evidence propagation is directional: strong name → establishes account →
  plausible name variants on that account accepted (with separate-entity
  override logic and account reuse filtering).

#### Pass 3 — Distractor Sanity Check

For rows NOT on established accounts, apply the hard separate-entity filter.
For rows on established accounts, they were already vetted in Pass 2.
This pass catches any rows that slipped through via name-only matching
but are actually separate entities on non-target accounts.

### Step 4: Output

Write matching rows as a JSON array:
- One object per row with keys matching the CSV columns exactly
- All values preserved as strings (including amounts with `$` and `-` signs)
- Sorted by `Date` ascending
- No top-level wrapper object

## Implementation

The companion script `solve.py` implements this algorithm.

### Usage

```bash
python3 solve.py [--target "Company Name"] [--input path.csv] [--output path.json]
```

Environment variables (override defaults):
- `TARGET_COMPANY`: The canonical target company name
- `INPUT_CSV`: Path to input CSV
- `OUTPUT_JSON`: Path to output JSON

### Common Abbreviation Expansions

| Abbreviation | Expansion |
|---|---|
| Cap. / Cap | Capital |
| Hldgs / Hldg | Holdings |
| Co | Company |
| Corp | Corporation |
| Inc | Incorporated |
| Ltd | Limited |
| Svc / Svcs | Services |
| Mfg | Manufacturing |
| Intl | International |
| Tech | Technology |
| Sys | Systems |
| Grp | Group |
| Ent / Entp | Enterprises |

### Key Principles

1. **Evidence propagation is directional and multi-step**: Strong name matches
   establish accounts. Accounts with multiple anchor rows are strongly established.
   Single-anchor accounts that are near-misses (1-2 char edit distance) of
   established accounts are excluded as likely typos. Once an account is
   established, rows with plausible name variants on that account are accepted.
   But rows with completely unrelated company names on shared accounts are
   excluded (account reuse patterns). A weak name match alone on a new account
   is not enough to establish it — especially if the account is suspiciously
   similar to an established one.

2. **Separate-entity detection is a signal, not a hard gate**: Names with
   designators like `Advisors`, `Partners`, `Advisory` are flagged as potential
   separate entities. In Pass 1 (anchor discovery), this is a hard exclusion
   because anchors must be high-confidence. In Pass 2 (account propagation),
   the flag is overridable: if the row sits on an established target account
   AND its core name (after stripping designators) matches the target, the
   account evidence + core name consistency together constitute the "consistent
   evidence" the spec requires for inclusion.

3. **Account numbers are exact identifiers, but accounts can be shared**: Never
   fuzzy-match account numbers. `BUS-41777` and `BUS-41877` are different
   accounts. If a name-matched row proposes a new account that is a near-miss
   (1-2 char edit distance) of an already-established target account, it is
   likely a typo and should be excluded. However, accounts can be shared
   between entities (account reuse): a row on an established target account
   with a completely unrelated company name should be excluded, while a row
   with a shorter/abbreviated alias of the target should be included.

4. **Abbreviation expansion is symmetric**: When comparing initials-based names
   to target names, abbreviations are expanded on BOTH sides. This prevents
   false negatives when the target itself contains abbreviations (e.g., target
   "North West Capital Co" vs variant "N.W. Capital Co" — both expand "co" to
   "company" before comparison).

5. **Legal suffixes and designators are stripped in layers**: First legal
   suffixes (Group, Holdings, LLC, etc.) are stripped from the end. Then
   designator words (Advisors, Partners, etc.) are removed. Then legal suffixes
   are stripped again (because removing a designator may expose a suffix that
   was previously not at the end, e.g., "Capital Holdings Advisors" → strip
   "Advisors" → "Capital Holdings" → strip "Holdings" → "Capital").

6. **When in doubt, exclude**: Precision matters more than recall. It is better
   to miss a borderline row than to include a distractor.

7. **Initials are valid aliases**: `N.W.` is a valid abbreviation for
   `North West`. The matching algorithm checks if single-letter words at the
   start of a name correspond to the initial letters of target words.

8. **Compound words normalize**: `Northwest` and `North West` should be treated
   as equivalent for matching purposes (applies to all compound directions).
