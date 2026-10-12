---
name: bank-trans-filter
description: >
  Filter bank transaction CSV rows to retain only those belonging to a target
  company, handling noisy entity identifiers including abbreviation variants,
  legal-suffix variations, spelling drift, punctuation changes, and
  account-number-based identity propagation. Excludes separately-named entities
  (advisors, partners, subsidiaries) that superficially resemble the target.
---

# Bank Transaction Filter

## Task Summary

Given a CSV file of bank transactions and a target company name (extracted from
the task instruction), retain only the rows belonging to that company and write
them as a sorted JSON array.

## Key Challenges

1. **Company name variation**: The same company appears under multiple name forms
   — abbreviations (`N.W.` for `North West`), truncated words (`Cap.` for
   `Capital`, `Hldgs` for `Holdings`), legal-suffix changes (`Group`,
   `Holdings`, `Inc`, `LLC`), spelling merges (`Northwest` vs `North West`),
   and punctuation differences.

2. **Separate-entity exclusion**: Names like `North West Capital Advisors` or
   `Northwest Capital Partners` contain the target's core name but represent
   *different organizations*. Words like `Advisors`, `Partners`, `Advisory`,
   `Consulting` signal a separate entity, not a legal-suffix variation.

3. **Account-number propagation**: An account number established as belonging to
   the target (via a clear name match on at least one row) can include other
   rows on that same account even if their name alias is shorter or less clear.

4. **Account numbers are exact identifiers**: Do NOT fuzzy-match account numbers.
   `BUS-41877` and `BUS-41777` are different accounts even though they differ by
   one character. However, if the *company name* on `BUS-41877` independently
   matches the target, that row is included based on the name match.

## Solution Approach

### Step 1: Extract Target Company Name

Parse the task instruction for the pattern:
```
Keep only the transactions that belong to <TARGET COMPANY>.
```
Extract `<TARGET COMPANY>` as the target name.

### Step 2: Name Matching with Entity Resolution

For each unique company name in the CSV, determine if it is a variant of the
target using this pipeline:

#### 2a. Normalize
- Lowercase
- Replace punctuation (`.`, `-`, `_`, `,`, `;`, `'`, `"`) with spaces
- Collapse whitespace

#### 2b. Strip Legal Suffixes
Remove trailing words that are legal-entity suffixes (not entity-type indicators):

**Legal suffixes** (same entity, different legal form):
`holdings`, `hldgs`, `group`, `grp`, `incorporated`, `inc`, `corporation`,
`corp`, `limited`, `ltd`, `company`, `co`, `plc`, `llc`, `llp`, `gmbh`,
`ag`, `sa`, `pty`, `pte`, `enterprises`, `ventures`

Strip iteratively from the end while more than one word remains.

#### 2c. Expand Abbreviations
Build an abbreviation map from the target name's words:
- First-letter initials: `N` → `North`, `W` → `West`
- Dotted initials: `N.` → `North`, `W.` → `West`
- Multi-letter initials: `NW` → `North West`, `N.W.` → `North West`
- Truncations (3-4 chars): `Cap` → `Capital`, `Hldg` → `Holdings`
- Fused spelling variants: `northwest` → `north west`

Apply the map to the company name tokens.

#### 2d. Compare
After normalization + suffix stripping + abbreviation expansion, compare with
the normalized target (also suffix-stripped). If they match, the name is a
genuine variant.

#### 2e. Prefix-Similarity Fallback
If all exact-match attempts fail, compare token sets using a "common prefix"
test. Two tokens match if they share a common prefix of at least 3 characters.
This handles truncation-based abbreviations at any length without enumerating
them:
- `trade` ↔ `trading` (common prefix `trad`, 4 chars)
- `intl` ↔ `international` (common prefix `int`, 3 chars)
- `cap` ↔ `capital` (common prefix `cap`, 3 chars)
- `assoc` ↔ `associates` (common prefix `assoc`, 5 chars)

Require ALL tokens to match (same token count, each pair shares a prefix).
The entity-type-indicator guard (Step 2f) prevents false positives.

#### 2f. Entity-Type Indicator Check
Even if a name partially matches, check for **entity-type indicator** words
that signal a *separate organization*:

`advisors`, `advisory`, `adviser`, `partners`, `partner`, `consulting`,
`consultants`, `services`, `solutions`, `technologies`, `tech`, `management`,
`brokerage`, `broker`, `trust`, `bank`, `fund`, `energy`, `airlines`,
`shipping`, `manufacturing`, `construction`, `engineering`, `pharmaceuticals`,
`medical`, `insurance`

If the company name contains extra words (beyond the target's words and legal
suffixes) that are entity-type indicators → **exclude** (separate entity).

### Step 3: Guarded Iterative Account-Number Propagation

1. Collect all account numbers from rows that matched by name (Step 2).
2. For remaining rows on those accounts, apply a **contradiction guard**:
   - Expand abbreviations in the row's company name
   - If the name has entity-type indicators not in the target → reject
   - If no word in the name shares even a prefix with any target word → reject
   - Otherwise → include (conservative: ambiguous names are included)
3. **Iterate until stable**: newly included rows may establish new account
   numbers, which may propagate to more rows. Repeat Steps 2+3 until no new
   rows are discovered. This handles chained evidence patterns where identity
   propagates across multiple hops.

### Step 4: Output

- JSON array (no wrapper object)
- One object per row with keys: `Company Name`, `Account Number`, `Date`,
  `Amount`, `Transaction Type`, `Description`
- All values are strings preserved exactly from the CSV
- Sorted by `Date` ascending

## Implementation

The skill package includes `solve.py` which implements the full pipeline.
To use it, first locate the script (it sits alongside this SKILL.md in the
skill package) and copy it into the container, then run:

```bash
# The skill package is mounted at /skill/ in the container.
# Copy the solver to a writable location:
cp /skill/solve.py /app/solve.py 2>/dev/null

# Run with the target company name extracted from the instruction:
python3 /app/solve.py \
  --target "TARGET COMPANY NAME" \
  --input /app/data/bank_transactions.csv \
  --output /app/data/output.json
```

If the script is unavailable, implement the pipeline described above directly
in Python. The key steps are:
1. Parse the target name from the instruction
2. For each CSV row, check name match (normalize → strip legal suffixes →
   expand abbreviations → compare → prefix-similarity fallback) and absence
   of entity-type indicators
3. Collect matched account numbers, propagate to additional rows on those
   accounts with a contradiction guard (reject names with entity-type
   indicators or zero shared prefixes with the target)
4. Iterate steps 2-3 until stable
5. Sort by Date ascending, write as JSON array with exact string values

## Critical Rules

1. **Account numbers are exact**: Never treat near-miss account numbers as equal.
   Preserve them exactly as they appear in the CSV.
2. **Advisors/Partners are separate**: A name like `X Capital Advisors` is a
   different entity from `X Capital`, even though it contains the target's name.
3. **Abbreviations are contextual**: Build the abbreviation map from the actual
   target name, not from a fixed dictionary.
4. **Propagate conservatively**: Only propagate through account numbers that
   have been established by at least one clear name match. Guard propagation
   with a contradiction check to avoid including unrelated entities on shared
   accounts.
5. **Preserve all values exactly**: Do not modify, trim, or reformat any CSV
   values in the output.
6. **Prefix similarity is a fallback**: Use exact matching first; prefix-based
   token matching only after all exact attempts fail. The entity-type-indicator
   guard prevents false positives from broader matching.
