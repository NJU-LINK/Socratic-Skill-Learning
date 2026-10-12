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
   one character. A name match on a near-miss account is NOT sufficient for
   inclusion — the near-miss account is a distractor and must be excluded.

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

**Important:** This check only applies to words that are NOT part of the target
name. If the target is "Summit Investment Partners", then "investment" and
"partners" are part of the target and would NOT be flagged as entity-type
indicators.

**Warning:** Do not add business activity descriptors (securities, investments,
finance, assets, equity, etc.) to the entity-type indicator list. These describe
what a company DOES, not that it's a separate entity. A company named "X Capital"
can legitimately have rows labeled "X Capital Securities" or "X Capital Investments"
as divisions of the same entity. Entity-type indicators should describe an
organizational role or legal structure (advisors, partners, consulting), not a
business activity.

### Step 3: Near-Miss Account Detection

After finding all rows that match by name, detect and exclude **near-miss account
distractors** — accounts that differ by exactly one character from another
name-matched account.

1. Group name-matched rows by account number
2. For each pair of accounts, check if they differ by exactly one character
3. If yes, compare the evidence strength (row counts) of each account
4. **Evidence-asymmetry rule**: Only exclude when one account has clearly less
   evidence than the other:
   - Calculate the ratio: `max(count1, count2) / min(count1, count2)`
   - If ratio ≥ 2.0: exclude the account with fewer rows (likely a distractor)
   - If ratio < 2.0: **keep both** (comparable evidence suggests genuine multi-account entity)

This handles cases like `BUS-41877` (one row) being a near-miss of `BUS-41777`
(5 rows). The ratio is 5.0 ≥ 2.0, so `BUS-41877` is excluded as a distractor.

**Why evidence asymmetry?** When two near-miss accounts have comparable evidence
(e.g., both have 3+ rows with clear name variants), the correct inference is that
the company genuinely has two accounts that happen to be one character apart.
Excluding either would be a recall error. The 2.0 threshold balances precision
(excluding clear distractors) with recall (keeping genuine multi-account entities).

### Step 4: Guarded Iterative Account-Number Propagation

1. Collect all account numbers from rows that matched by name (Step 2) and
   survived near-miss detection (Step 3).
2. For remaining rows on those accounts, apply a **contradiction guard**:
   - Expand abbreviations in the row's company name
   - If the name has entity-type indicators not in the target → reject
   - If no word in the name shares even a prefix with any target word → reject
   - Otherwise → include (conservative: ambiguous names are included)
3. **Iterate until stable**: newly included rows may establish new account
   numbers, which may propagate to more rows. Repeat Steps 3+4 until no new
   rows are discovered. This handles chained evidence patterns where identity
   propagates across multiple hops.

### Step 5: Output

- JSON array (no wrapper object)
- One object per row with keys: `Company Name`, `Account Number`, `Date`,
  `Amount`, `Transaction Type`, `Description`
- All values are strings preserved exactly from the CSV
- Sorted by `Date` ascending

## Decision Logic Summary

The filtering process follows this decision tree:

1. **Extract target name** from instruction (pattern: "belong to <TARGET>.")

2. **For each unique company name in CSV**, determine if it's a target variant:
   - Normalize (lowercase, remove punctuation, collapse whitespace)
   - Strip legal suffixes (Group, Holdings, Inc, etc.)
   - Expand abbreviations (N.W. → North West, Cap. → Capital, etc.)
   - Compare with normalized target
   - If exact match fails, try prefix-similarity fallback (min 3 common chars)
   - **If match found**: Check for entity-type indicators in extra words
     - If entity-type indicators present → **EXCLUDE** (separate entity)
     - Otherwise → **MATCH** (genuine variant)

3. **Near-miss account detection** (after finding all name matches):
   - Group matched rows by account number
   - For each pair of accounts differing by one character:
     - Calculate evidence ratio: max(count1, count2) / min(count1, count2)
     - If ratio ≥ 2.0 → exclude weaker account (distractor)
     - If ratio < 2.0 → keep both (genuine multi-account entity)

4. **Account propagation** (iterative):
   - Collect account numbers from matched rows
   - For each remaining row on those accounts:
     - Check for name contradictions (entity-type indicators or zero shared prefixes)
     - If no contradiction → **INCLUDE** (add to matched set)
   - Repeat until no new rows are added

5. **Output**: Sort by Date ascending, write as JSON array with exact string values

## Common Pitfalls

1. **Over-matching on similar names**: Just because a company name contains some of the target's words doesn't mean it's the same entity. Always check for entity-type indicators (Advisors, Partners, Consulting, etc.) that signal a separate organization. Note: business activity descriptors like "Securities" or "Investments" are NOT entity-type indicators.

2. **Under-matching on name variants**: The same company can appear under many different name forms. Use the full pipeline (normalize → strip suffixes → expand abbreviations → prefix similarity) to catch all variants.

3. **Including near-miss accounts**: When two accounts differ by one character, use evidence asymmetry to decide which (if either) to exclude. Don't arbitrarily include or exclude based on CSV row order.

4. **Propagating without contradiction checks**: When including rows on established accounts, always check that the company name doesn't contradict the target. A row with a completely different company name on a target account is likely a data error.

5. **Stopping propagation too early**: Identity evidence can chain across multiple hops (name → account → shorter alias → new account). Iterate until no new rows are discovered.

6. **Fuzzy-matching account numbers**: Account numbers are exact identifiers. Never treat BUS-41877 and BUS-41777 as the same account, even though they differ by one character.

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
3. Detect near-miss account distractors: if two name-matched accounts differ
   by exactly one character, exclude the one with fewer rows
4. Collect matched account numbers, propagate to additional rows on those
   accounts with a contradiction guard (reject names with entity-type
   indicators or zero shared prefixes with the target)
5. Iterate steps 3-4 until stable
6. Sort by Date ascending, write as JSON array with exact string values

## Critical Rules

1. **Account numbers are exact**: Never treat near-miss account numbers as equal.
   Preserve them exactly as they appear in the CSV. If two accounts differ by
   one character, they are DIFFERENT accounts.
2. **Near-miss accounts: use evidence asymmetry**: When two accounts differ by
   one character, compare their evidence strength (row counts). Only exclude
   the weaker account when the evidence ratio ≥ 2.0. When evidence is comparable
   (ratio < 2.0), keep both — they may be genuine multi-account entities.
3. **Advisors/Partners are separate**: A name like `X Capital Advisors` is a
   different entity from `X Capital`, even though it contains the target's name.
4. **Abbreviations are contextual**: Build the abbreviation map from the actual
   target name, not from a fixed dictionary.
5. **Propagate conservatively**: Only propagate through account numbers that
   have been established by at least one clear name match. Guard propagation
   with a contradiction check to avoid including unrelated entities on shared
   accounts.
6. **Preserve all values exactly**: Do not modify, trim, or reformat any CSV
   values in the output.
7. **Prefix similarity is a fallback**: Use exact matching first; prefix-based
   token matching only after all exact attempts fail. The entity-type-indicator
   guard prevents false positives from broader matching.
