---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a target company,
  using evidence-proportional reconciliation across name and account dimensions.
  Strong matches (compact containment) establish accounts ordered by evidence strength;
  weak matches (edit distance) only ride along on established accounts. Near-miss
  account numbers are rejected only when their evidence is disproportionately weak
  relative to established accounts. Dotted abbreviation pre-processing (N.W. -> nw)
  enables safe abbreviation expansion without aggressive single-letter matching.
  Handles legal-suffix normalization, token-overlap pre-filtering, and exclusion of
  advisors/partners/subsidiaries.
---

# Bank Transaction Filter

## Task Summary

Given a CSV of bank transactions and a target company name, extract all transactions
belonging to that company. The same company may appear under multiple name variants
and account numbers. Write the result as a sorted JSON array.

## Input / Output Contract

- **Input**: CSV file at `/app/data/bank_transactions.csv` with columns including
  `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`.
- **Output**: JSON array at `/app/data/output.json` — one object per matching row,
  with exactly the CSV column keys, sorted by `Date` ascending, all values as strings
  preserved exactly from the CSV.

## Target Name Extraction

The target company name is specified in the task instruction. Extract it from
phrases like:
- "Keep only the transactions that belong to **X**."
- "Filter for **X**."
- "Extract transactions for **X**."

Pass the extracted name as the first argument to `solve.py`:
```bash
python3 solve.py "Target Company Name"
```

## Algorithm: Evidence-Proportional Reconciliation

### Core Principle

When a row's name says "target" but its account is a near-miss of an established
account, we have **conflicting evidence across two identifier dimensions**:
- **Name evidence**: strong match -> "this IS the target company"
- **Account evidence**: near-miss -> "this account number might be corrupted"

The correct decision depends on the **weight of evidence behind the near-miss account**,
not just its existence. A near-miss with strong independent evidence (multiple rows)
is likely a legitimate separate account with a coincidentally similar number. A
near-miss with only 1-2 rows is likely a typo.

**Trust an identifier only when the corroborating evidence on the OTHER identifier
dimension is strong enough to override the concern raised by this dimension.**

### Layer 1: Name Normalization

**Step 1 — Dotted abbreviation pre-processing**: Before general punctuation removal,
join dotted single-letter abbreviations into a single token:
- "N.W." -> "nw" (then expanded to "north west" via abbreviation dictionary)
- "N.W" -> "nw"
- "U.S.A." -> "usa"
- "N Capital" -> "n capital" (standalone "n" NOT expanded — it might mean "National")

This is critical: it allows "N.W. Capital Holdings" to match "North West Capital"
while preventing "N Capital Group" from falsely matching (where "N" might stand
for "National", not "North").

**Step 2 — General normalization**:
1. **Lowercase** the string
2. **Remove punctuation**: replace `.,;:'"()-/&` with spaces
3. **Collapse whitespace** to single spaces
4. **Expand abbreviations** using a dictionary (e.g., `nw` -> `north west`,
   `cap` -> `capital`, `hldgs` -> `holdings`, `co` -> `company`, `ltd` -> `limited`)
5. **Strip legal suffixes** from the end of the token list (e.g., `group`,
   `holdings`, `llc`, `inc`, `ltd`, `corp`, `trust`, `fund`)

**Important**: Legal suffixes are strictly structural indicators (LLC, Inc, Group,
Holdings, etc.). Core identity words like "capital", "management", "solutions" are
NOT stripped because they distinguish different entities.

### Layer 2: Name Matching with Confidence Tiers

For each row, determine whether its `Company Name` matches the target:

1. **Exclusion check** -> `None`: If the company name contains words like `advisors`,
   `advisory`, `partners`, `partnership`, `subsidiary`, `affiliates`, `division`,
   `branch` -> REJECT. These indicate a *different* entity even if other words
   overlap with the target.

2. **STRONG — Compact containment with extra-core-token guard** -> `'strong'`: Join
   the core tokens into a single string with no spaces. If the target's compact form
   is a substring of the company's compact form **AND** the company has no extra core
   tokens beyond the target's core tokens -> STRONG MATCH.
   
   **Extra-core-token guard**: If the company has more core tokens than the target
   (after abbreviation expansion and legal-suffix stripping), the extra tokens suggest
   a different entity (e.g., a subsidiary like "North West Capital Management" vs
   target "North West Capital"). Such matches are downgraded to `'weak'`.
   
   **Strong matches can establish accounts.**

3. **Token overlap pre-filter** -> `None`: Before attempting edit distance, require
   that the company shares at least 50% of the target's core tokens.

4. **WEAK — Edit distance fallback or downgraded containment** -> `'weak'`: Either
   (a) Levenshtein distance between compact forms <= max(2, len(target_compact) // 6),
   or (b) containment succeeded but the company has extra core tokens.
   
   **Weak matches cannot establish accounts; they only ride along.**

### Layer 3: Account Establishment with Evidence-Proportional Reconciliation

**Evidence-strength ordering**: Accounts are established in order of how many
strong-match rows they have. Accounts with more corroborating evidence are
established first.

**Evidence-proportional near-miss rejection**: When considering a new account
for establishment, check if its account number is a near-miss (Levenshtein
distance <= 2) of any already-established account. If so, reject it **only if**
its evidence is disproportionately weak:

```python
if new_count < max(2, est_count * 0.5):
    # Reject: evidence too weak to override near-miss concern
else:
    # Accept: strong independent evidence suggests legitimate separate account
```

**Algorithm**:
1. Group all strong-match rows by account number
2. Sort accounts by number of strong-match rows (descending)
3. For each account (most evidence first):
   - If it's a near-miss of an established account AND its evidence is weak -> SKIP
   - Otherwise -> ESTABLISH (add to established set, include all its rows)
4. Include ALL rows on established accounts (even non-matching names)

### Layer 4: Weak Match Integration and Fallback

**Weak matches**: After strong accounts are established, include any weak-match
rows that are on established accounts.

**Fallback**: If no strong matches exist at all, promote weak matches to
account-establishing status (with the same evidence-proportional reconciliation).

### Layer 5: Output Assembly

1. Collect all matching row indices
2. Build JSON objects with exactly the CSV column keys
3. Sort by `Date` ascending (lexicographic on ISO date strings)
4. Write as a JSON array (no top-level wrapper)

## Key Design Decisions

### Why dotted abbreviation pre-processing?

Without it, "N.W." would be split into ["n", "w"] after punctuation removal,
requiring single-letter expansions (n->north, w->west). But standalone "N" in
"N Capital Group" would also be expanded to "north", causing false matches
when "N" means "National" or is just an initial.

With dotted pre-processing, "N.W." is joined to "nw" BEFORE general normalization,
so only the multi-letter abbreviation "nw" needs to be in the dictionary. Standalone
"N" is never expanded, preventing false positives.

### Why not strip "capital", "management", "solutions" as suffixes?

These are core identity words that distinguish different entities:
- "North West Capital" and "North West Capital Management" are DIFFERENT companies
- "Summit Investment" and "Summit Investment Solutions" are DIFFERENT companies

Stripping them would cause false containment matches. Only structural legal
suffixes (LLC, Inc, Group, Holdings, etc.) should be stripped.

### Why the extra-core-token guard?

Containment alone is too permissive. A company like "North West Capital Management"
contains the target "North West Capital" as a prefix, but the extra token "management"
indicates a separately named entity (likely a subsidiary). Without the guard, such
companies would be STRONG matches and could establish their own accounts, pulling in
all their subsidiary rows.

The guard downgrades containment-with-extra-tokens to WEAK. This means:
- The subsidiary cannot establish its own account (prevents false account creation)
- If the subsidiary shares an account with the target, its rows are still included
  via account propagation (the name match isn't needed)
- The evidence-proportional reconciliation at the account level provides a second
  layer of defense

This gives two independent guards against containment over-matching:
1. **Layer 1 (name)**: extra-core-token guard downgrades to weak
2. **Layer 2 (account)**: evidence-proportional reconciliation rejects weak-evidence accounts

### Why evidence-strength ordering?

If a typo account appeared first chronologically, chronological ordering would
establish it first, then reject the real account as a near-miss. Evidence-strength
ordering always establishes the account with more corroborating evidence first.

### Why the threshold `max(2, est_count * 0.5)`?

- **Minimum of 2**: Even if the established account has only 1 row, we require
  at least 2 rows to override a near-miss concern
- **50% ratio**: If the established account has 10 rows, the near-miss needs
  at least 5 rows to be accepted

## Abbreviation Dictionary

Multi-letter abbreviations only (single-letter dotted abbreviations handled by
pre-processing):
- **Directional**: nw->north west, ne->north east, sw->south west, se->south east
- **Financial**: cap->capital, hldgs->holdings, fin->financial, inv->investment
- **Entity types**: co->company, corp->corporation, inc->incorporated, ltd->limited
- **Operational**: svc->service, mgmt->management, tech->technology, sys->systems
- **Industry**: mfg->manufacturing, pharm->pharmaceuticals, aero->aerospace

## Variation Dimensions (from spec)

1. **Company identity signal variation**: Spelling drift, abbreviations, legal-suffix
   changes, partial-name matches, identifier corruption.
   -> Normalization + abbreviation expansion + two-tier matching.

2. **Transaction membership inference**: Multiple accounts, sparse anchors, indirect
   membership, identifier reconciliation.
   -> Evidence-proportional reconciliation + account propagation.

3. **Distractor entity confusability**: Overlapping names, near-miss accounts,
   subsidiaries/partners.
   -> Exclusion words + token overlap pre-filter + evidence-proportional near-miss
   rejection + exact account matching.

## Usage

```bash
# Extract target name from instruction, then:
python3 solve.py "Target Company Name"
python3 solve.py "Target Company Name" /path/to/input.csv /path/to/output.json
TARGET_NAME="Target Company Name" python3 solve.py
```

## Edge Cases

1. **No strong matches**: Fallback promotes weak matches (with reconciliation).
2. **Target name contains exclusion words**: Exclusion only applies to data rows.
3. **Account number shared by multiple entities**: Exact string matching, no fuzz.
4. **Very short target names**: Edit distance threshold scales with target length.
5. **Typo account first chronologically**: Evidence-strength ordering handles this.
6. **Legitimate near-miss account**: Accepted when evidence is strong enough.
7. **Standalone single letters in names**: NOT expanded (might be initials).
8. **Dotted abbreviations (N.W., U.S.A.)**: Joined before normalization, then expanded.
9. **Subsidiary with extra tokens**: "North West Capital Management" contains target
   "North West Capital" but has extra token "management" -> downgraded to WEAK ->
   cannot establish its own account -> only included if on an established account.
