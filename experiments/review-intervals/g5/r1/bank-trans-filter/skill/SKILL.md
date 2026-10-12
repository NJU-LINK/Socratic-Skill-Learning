---
name: bank-trans-filter
description: Entity-resolution filtering of bank transactions to extract rows belonging to a target company, using anchor-and-expand with evidence propagation across name variants and account numbers.
---

# Bank Transaction Filter

## Problem

Filter bank transaction CSV files to extract only rows belonging to a target company specified in the instruction text. The target company may appear under multiple name variants (punctuation, abbreviations, spelling variations, legal-suffix changes) and multiple account numbers. The skill must:

1. Identify all rows belonging to the target entity
2. Handle name normalization and abbreviation expansion
3. Propagate entity membership from name matches to account numbers
4. Exclude distractor entities with superficially similar names
5. Exclude near-miss accounts (1-character variants) as corrupted distractors while preserving exact account values for included rows

## Algorithm: Anchor-and-Expand

### Phase 1: Parse Target Name

Extract the target company name from the instruction text. The instruction typically states: "Keep only the transactions that belong to **[Target Company]**."

### Phase 2: Normalize Names

Normalize all company names for comparison:

1. **Lowercase** the entire name
2. **Extract dotted initialisms** (e.g., "N.W." → letters `['n', 'w']`). Requires 2+ letter-dot sequences to avoid false matches on abbreviations like "Cap."
3. **Expand known abbreviations** using a dictionary:
   - `co` → `company`, `corp` → `corporation`, `inc` → `incorporated`
   - `ltd` → `limited`, `llc` → `limited liability company`
   - `hldgs` → `holdings`, `cap` → `capital`, `svcs` → `services`
   - `mgmt` → `management`, `intl` → `international`, `tech` → `technology`
   - `sys` → `systems`, `dev` → `development`, `mfg` → `manufacturing`
4. **Remove punctuation** and normalize whitespace
5. **Tokenize** into word list

### Phase 3: Anchor — Find Target Rows by Name

For each row, determine if its normalized name matches the target:

**Step 3a: Check for distinguishing suffixes FIRST**

Before any similarity matching, check if the row name contains a **distinguishing suffix** that indicates a different entity:
- `advisors`, `advisory`, `adviser`, `partners`, `associates`
- `consultants`, `consulting`, `management`, `services`, `solutions`
- `ventures`, `investments`

If the row name contains one of these suffixes AND the target name does NOT contain it, **reject the row** — it's a different entity even if the core name overlaps.

**Step 3b: Initialism matching**

If the row name has a dotted initialism (e.g., "N.W."), check if the letters match the target tokens positionally by prefix:
- Letter `n` matches target word `north` (starts with 'n')
- Letter `w` matches target word `west` (starts with 'w')
- All initialism letters must match corresponding target words

If initialism matches, check if remaining tokens are a subset of target tokens (after stripping legal suffixes).

**Step 3c: Token containment**

Compute **core containment similarity**: strip legal-form suffixes from both names, then compute bidirectional containment. Requirements:
- **Minimum overlap**: 3 core tokens (prevents false positives from short names)
- **Bidirectional containment**: both forward (candidate/target) and backward (target/candidate) must be ≥ 0.5

If score ≥ 0.6, accept the row.

This prevents short names like "Capital" or "North West" from matching "North West Capital" — they lack sufficient token overlap.

**Step 3d: Character similarity fallback**

If token containment fails, compute character-level similarity (sequence matcher ratio). If ≥ 0.8, accept the row.

### Phase 4: Expand — Propagate by Account Number

Collect all account numbers from anchor rows. Then include **all rows** on those accounts, even if their company name is abbreviated or unclear. This is the key insight: **account number is ground truth for entity membership once established**.

**Critical: Near-Miss Account Handling**

When processing anchor rows to establish target accounts:
- If an anchor's account **exactly matches** an existing target account → include
- If an anchor's account is a **1-character near-miss** of an existing target account → **EXCLUDE it** (corrupted/distractor account)
- Otherwise → establish as new target account

An account that differs by exactly 1 character from an already-established target account is treated as a **corrupted distractor**, even if the name matches. The instruction explicitly states: "do not treat one-character-near account numbers as equal." This prevents false positives from identifier corruption.

### Phase 5: Output

Write matching rows to `/app/data/output.json`:
- JSON array (no top-level wrapper)
- One object per row with exactly these keys: `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`
- Sorted by `Date` ascending
- All values as strings preserved exactly from CSV (including `$`, `-`, formatting)

## Key Principles

### Account Number is Ground Truth

Once entity membership is established (via name matching), the account number becomes the authoritative identifier. All rows on that account belong to the target, even if the company name is abbreviated or varies.

### Legal-Form Suffixes Don't Distinguish Entities

These suffixes are interchangeable and do NOT indicate different entities:
- `group`, `holdings`, `hldgs`, `corp`, `corporation`, `inc`, `incorporated`
- `ltd`, `limited`, `llc`, `plc`, `co`, `company`, `lp`, `llp`
- `pc`, `na`, `trust`, `fund`

"Capital Group" and "Capital Holdings" can be the same entity.

### Distinguishing Suffixes DO Indicate Different Entities

These suffixes indicate a **different legal entity** and must be checked BEFORE similarity matching:
- `advisors`, `advisory`, `adviser` — advisory firm, not the capital entity
- `partners`, `associates` — partnership entity
- `consultants`, `consulting` — consulting firm
- `management`, `services`, `solutions` — service provider
- `ventures`, `investments` — investment entity

"North West Capital Advisors" is a different entity from "North West Capital Group", even though they share the core name.

### Initialisms Require Positional Matching

Dotted initialisms like "N.W." match target words by position:
- First letter must start first target word
- Second letter must start second target word
- All letters must match

This prevents false matches like "W.N. Capital" matching "North West Capital".

### Account Numbers are Identifiers, Not Numbers

Preserve account numbers exactly as they appear. Do not treat one-character-near account numbers as equal — **even if** the name matches, a near-miss account is a corrupted distractor, not a typo to recover.

### Name Matching Requires Bidirectional Containment

Token containment must be bidirectional with minimum overlap of 3 core tokens:
- Candidate must cover ≥ 50% of target tokens
- Target must cover ≥ 50% of candidate tokens
- At least 3 tokens must overlap

This prevents short names ("Capital", "North West") from matching longer names ("North West Capital") — they lack sufficient bidirectional overlap. The initialism path (Step 3b) handles abbreviated names like "N.W. Capital Holdings" separately.

## Reference Implementation

The working algorithm is implemented in `scripts/solve.py`. The script:
- Reads from `/app/data/bank_transactions.csv`
- Writes to `/app/data/output.json`
- Implements all phases of the anchor-and-expand algorithm
- Handles abbreviation expansion, initialism matching, suffix filtering
- Propagates entity membership via account numbers
- Excludes near-miss accounts (1-character variants) as corrupted distractors

## Generalization

This skill generalizes to any target company, not just the v01 example. The algorithm:
- Extracts target name from instruction text (not hardcoded)
- Uses token containment + initialism matching (not regex patterns for specific names)
- Applies legal-suffix stripping and distinguishing-suffix filtering (domain knowledge about business naming)
- Propagates via account numbers (works for any entity with multiple accounts)
- Excludes near-miss accounts as corrupted distractors (prevents false positives from identifier corruption)

The skill handles the full variation space described in the spec:
- **Company identity signal variation**: Multiple name variants, abbreviations, initialisms, spelling drift
- **Transaction membership inference**: Evidence propagation from name to account, multiple accounts per entity
- **Distractor entity confusability**: Distinguishing suffixes, near-miss accounts, superficially similar names
