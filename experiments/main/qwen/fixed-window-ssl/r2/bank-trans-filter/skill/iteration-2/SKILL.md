---
name: bank-trans-filter
description: Filter bank transactions to extract only those belonging to a target company using token-level fuzzy matching, bidirectional evidence scoring, and iterative fixpoint propagation to handle name variations, abbreviations, typos, and account-based evidence propagation.
---

# Bank Transaction Filter

## Problem

Given a CSV file of bank transactions with columns `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, and `Description`, extract all transactions belonging to a specified target company. The challenge is that the target company may appear under multiple name variants (abbreviations, typos, legal suffix changes, partial names) and may have multiple account numbers. Some rows may be distractors with similar names or account numbers.

## Core Approach

### 1. Token-Level Fuzzy Matching

Instead of regex-based pattern matching (which is brittle to spelling variations), decompose company names into tokens and compute similarity at the token level.

**Tokenization:**
- Remove punctuation (periods, commas, hyphens, parentheses)
- Split on whitespace
- Lowercase all tokens

**Abbreviation handling:**
- Maintain a dictionary mapping common abbreviations to full forms (e.g., `co` → `company`, `corp` → `corporation`, `grp` → `group`, `hldgs` → `holdings`, `cptl` → `capital`)
- Expand abbreviations before scoring

**Initialism handling:**
- Single-letter tokens (e.g., `n`, `w` from `N.W.`) should match the first letter of target tokens
- This handles cases like "N.W. Capital" matching "North West Capital"

**Compound word handling:**
- Some names merge words (e.g., "Northwest" instead of "North West")
- Use target-guided splitting: for each compound token, check if it can be decomposed into multiple target tokens
- For each split position, check if left/right parts are good fuzzy matches (≥0.7 similarity) for any target tokens
- Also check if the token contains a target token as substring, and if the remainder matches another target token
- This is more robust than arbitrary length cutoffs and handles cases like "nwcapital" (abbreviation + merged word)

### 2. Bidirectional Evidence Scoring

For each candidate company name, compute a score based on two criteria:

**Target coverage (70% weight):**
- For each target token, find the best-matching candidate token
- Target coverage = minimum similarity across all target tokens
- This ensures ALL identity-bearing words are present (with fuzzy tolerance)
- Prevents false positives like "Capital Group LLC" matching when only "capital" is present

**Candidate fit (30% weight):**
- For each non-legal-suffix candidate token, check if it matches any target token
- Candidate fit = fraction of candidate tokens that have a reasonable match (≥0.5 similarity)
- Penalizes names with many extra unrelated words

**Similarity function:**
Combine multiple similarity measures:
- Exact match: 1.0
- Abbreviation expansion match: 0.95
- Initialism match (single letter = first letter of target): 0.85
- Sequence similarity (edit distance ratio)
- Character overlap ratio
- Substring containment

Use the maximum of these measures for robustness.

### 3. Legal Suffixes vs Differentiating Suffixes

**Legal suffixes** (variation-tolerant, not identity-bearing):
- `group`, `holdings`, `hldgs`, `inc`, `ltd`, `llc`, `co`, `corp`, etc.
- These don't change entity identity and shouldn't penalize matching

**Differentiating suffixes** (change entity type):
- `advisors`, `advisory`, `partners`, `consultants`, `associates`, `agents`, `brokers`
- These indicate a different entity (e.g., "North West Capital Advisors" is not the same as "North West Capital Group")
- Rows with differentiating suffixes are excluded UNLESS account evidence overrides

### 4. Threshold-Based Anchor Detection

Use a score threshold (e.g., 0.55-0.60) to identify anchor rows:
- Rows with score ≥ threshold AND no differentiating suffix → anchor rows
- Anchor rows establish account numbers as belonging to the target
- This gracefully handles severe spelling drift (e.g., "Nrth Wst Cptl Grp" would still score high)

### 5. Iterative Fixpoint Propagation

Instead of two-pass filtering, use iterative propagation until no changes occur:

```
Repeat until no change:
  1. For all rows: if score ≥ threshold AND no differentiating suffix → mark as anchor, add account to known_target_accounts
  2. For all rows on known_target_accounts: if no differentiating suffix → include
  3. For all rows on known_target_accounts WITH differentiating suffix → include only if the name still has strong target-token coverage (account override)
```

**Why this logic?**
- Step 1 establishes new anchors from high-confidence name matches
- Step 2 propagates to rows on established accounts (clean case)
- Step 3 handles the tricky case: if a row has a differentiating suffix (e.g., "Advisors") but is on an established target account, include it ONLY if the name still has strong target-token coverage. This prevents blindly including "North West Capital Advisors" on BUS-30001 just because the account is shared — the name must also show consistent evidence of being the target entity.

**Why iteration?**
- Handles chains of evidence: Row A establishes Account X, Row B on Account X has a different alias that establishes Account Y, Row C on Account Y is now identifiable
- Two passes aren't enough for chains of length > 2
- The spec explicitly mentions "sparse anchor rows that establish entity membership indirectly"

### 6. Near-Miss Account Detection and Exclusion

Account numbers are exact identifiers. When multiple potential target accounts are near-misses of each other (e.g., one character different), treat the one with fewer rows as a data entry error and **exclude it**.

**Detection logic (collect-then-prune approach):**

1. **Phase 1: Collect all potential target accounts**
   - Scan all rows with score ≥ threshold and no differentiating suffix
   - Collect all unique account numbers into a `potential_accounts` set

2. **Phase 2: Remove near-misses**
   - Compare all accounts in `potential_accounts` against each other
   - For each pair of near-miss accounts (edit distance ≤ 1):
     - Count rows for each account (only high-confidence rows)
     - Remove the account with fewer rows (likely the typo)
   - This avoids ordering dependencies that could occur in a fixpoint loop

3. **Phase 3: Propagate with clean account set**
   - Use the pruned `potential_accounts` as `known_target_accounts`
   - Mark all rows on these accounts as target rows
   - Apply differentiating suffix logic (include only if strong name coverage ≥ 0.7)

**Why collect-then-prune instead of fixpoint?**
- Avoids ordering bugs: if a typo account is processed before the real account, it could be incorrectly established
- Uses row count as a heuristic: more rows = more likely to be the correct account
- Simpler and more predictable than incremental near-miss checking

**Example:**
- Phase 1: Collect {BUS-30001, BUS-41777, BUS-41877}
- Phase 2: BUS-41777 and BUS-41877 are near-misses
  - BUS-41777 has 5 high-confidence rows
  - BUS-41877 has 1 high-confidence row
  - Remove BUS-41877 (fewer rows)
- Phase 3: Final target accounts = {BUS-30001, BUS-41777}

## Implementation Steps

1. **Parse target name:** Extract from task description (e.g., "North West Capital")
2. **Tokenize target:** Split into identity-bearing tokens
3. **Read CSV:** Load all transaction rows
4. **Score all rows:** Compute name score and check for differentiating suffix
5. **Identify initial anchors:** High score + no differentiating suffix → establish accounts
6. **Fixpoint iteration:** Propagate account evidence until stable
7. **Collect target rows:** All rows on established accounts
8. **Sort by date:** Ascending order as required
9. **Write output:** JSON array with exact CSV keys preserved as strings

## Output Format

- JSON array (no top-level wrapper)
- One object per matching row
- Keys: `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`
- All values as strings, preserved exactly from CSV
- Sorted by `Date` ascending

## Family Variations

This approach handles the spec's variation dimensions:

**Company identity signal variation:**
- Mild: "North West Cap. Group" vs "North West Capital Group" (punctuation, abbreviation)
- Severe: "Nrth Wst Cptl Grp" (spelling drift)
- Initialisms: "N.W. Capital" (dots removed, single letters)
- Compounds: "Northwest Capital" (merged words)
- Partial names: Shorter aliases on established accounts

**Transaction membership inference:**
- Multiple accounts per company
- Account reuse patterns (same account, different name variants)
- Sparse anchors (few high-confidence rows, propagation needed)
- Indirect evidence chains (A→X, B on X→Y, C on Y)

**Distractor entity confusability:**
- Similar names: "North West Capital Advisors" (differentiating suffix)
- Similar accounts: One-character differences in account numbers (treated as distinct)
- Subsidiaries/partners: Excluded unless account evidence overrides
- Near-matches: High score but different entity type → excluded

## Key Principles

1. **Token-level, not regex:** Regex creates brittle boundaries; token similarity handles drift gracefully
2. **Bidirectional scoring:** All target tokens must be present (coverage) AND candidate tokens should mostly match (fit)
3. **Threshold, not binary:** Fuzzy matching with tunable threshold handles severe variations
4. **Fixpoint iteration:** Handles chains of evidence propagation, not just two-pass
5. **Account evidence with name verification:** If account is established, trust it over name variations, BUT rows with differentiating suffixes still need strong name coverage (not just account sharing)
6. **Exact account matching with near-miss detection:** Account numbers are matched exactly. When a potential target account is a near-miss (edit distance ≤ 1) of an established target account, treat it as a data entry error and exclude it. Do NOT propagate evidence to near-miss accounts.
7. **Preserve exactly:** Output values must match CSV exactly (no normalization, no parsing of amounts)
