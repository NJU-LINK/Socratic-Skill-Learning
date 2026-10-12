---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a named target
  entity. Handles entity resolution across name variants (abbreviations,
  punctuation, spelling drift, legal-suffix changes) and propagates identity
  evidence through account numbers. Distinguishes the target from confusable
  distractors (functional-suffix entities, near-miss account numbers,
  superficially similar names).
---

# Bank Transaction Filter

## Task Summary

Given a CSV file of bank transactions and a target company name, produce a JSON
array of only the transactions belonging to that target entity. The target may
appear under multiple name variants and account numbers; distractor entities may
have similar names or nearly-identical account numbers.

## Core Algorithm: Four-Phase Evidence Propagation

### Phase 1 — Name-Based Matching

Identify all rows whose company name is a variant of the target entity.

**Normalization pipeline** (applied to each company name):

1. **Expand abbreviations**: Convert known abbreviations to their full forms.
   Common patterns:
   - Initial-based abbreviations: `N.W.` → `north west`, `N.W.C.` → `north west capital`
   - Truncated words: `Cap.` → `capital`, `Hldgs.` → `holdings`, `Intl.` → `international`
   - Merged words: `Northwest` → `north west` (split into component words)

2. **Strip legal/structural suffixes** that describe the same entity's corporate form:
   - `Group`, `Holdings`, `Hldgs`, `Inc`, `LLC`, `Corp`, `Co`, `Ltd`, `PLC`
   - These are **interchangeable** — `Capital Group` and `Capital Holdings` are the same entity.

3. **Clean punctuation and whitespace**: Remove non-alpha characters, collapse spaces.

4. **Compare normalized core** against the normalized target name.

**Functional-suffix exclusion** (applied BEFORE normalization):

Names with these suffixes describe **different business entities** and must be
excluded even if the core name matches:
- `Advisors`, `Advisory` — a consulting/advisory arm, not the entity itself
- `Partners` — a partnership entity, legally distinct
- `Consulting`, `Services` — service-provider entities
- Any other suffix indicating a separate business line or legal structure

**UNIVERSAL GATE:** Functional-suffix exclusion applies across **ALL phases**
(Phase 1, 2, 3, and 4). Even if Phase 3 mutual reinforcement suggests a match
based on name score and account proximity, rows with functional suffixes are
**always excluded**.

**Decision rule**: A name matches the target if and only if:
- It does NOT contain a functional-suffix indicator, AND
- Its normalized core (after abbreviation expansion and legal-suffix removal) matches the normalized target.

### Phase 2 — Account Propagation

After Phase 1, collect all account numbers that appeared on matched rows. Then
do a second pass: include any additional rows whose account number is in that
set, even if their company name is shorter, noisier, or doesn't directly match.

This handles cases where:
- A row uses an abbreviated alias that Phase 1 couldn't match directly
- The account number was established by a clear Phase 1 match
- The dataset requires propagating identity evidence across rows

**Critical constraint**: Account numbers are **identifiers, not numbers**. Do NOT
treat account numbers that differ by even one character as the same account.
`BUS-41877` and `BUS-41777` are different accounts. Near-miss similarity does
not imply identity.

### Phase 3 — Mutual Reinforcement (for corrupted identifiers)

In harder variants, both the company name AND account number may be corrupted:
- Name: `Nrth Wst Cptl Grp` (spelling drift, too corrupted for Phase 1)
- Account: `BUS-3000l` (letter `l` instead of digit `1`, doesn't match Phase 1 accounts)

Neither identifier alone is convincing, but **together** they form strong evidence.

**Three-tier evidence model:**

1. **Strong name match** (normalized score ≥ 0.95) → include standalone (Phase 1)
2. **Exact account** + weak name (score ≥ 0.5) → include (Phase 2)
3. **Medium name match** (score ≥ 0.7) + **near-miss account** (Levenshtein ≤ 2) → include (Phase 3)

**When to apply Phase 3:**
- The name is CORRUPTED (doesn't match in Phase 1)
- The account is a near-miss of an established target account
- Together, they provide enough evidence to include the row

**Implementation:**

```python
from difflib import SequenceMatcher

def fuzzy_similarity(s1, s2):
    """Return similarity ratio 0.0-1.0 between two strings."""
    return SequenceMatcher(None, s1, s2).ratio()

def levenshtein_distance(s1, s2):
    """Compute edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

# Phase 3: mutual reinforcement
HIGH_THRESHOLD = 0.95    # Strong name, standalone sufficient
MEDIUM_THRESHOLD = 0.7   # Recognizable but corrupted
ACCOUNT_NEAR_THRESHOLD = 2  # Levenshtein distance ≤ 2

for i, txn in enumerate(transactions):
    if i in matched_indices:
        continue
    
    # UNIVERSAL GATE: Functional-suffix exclusion applies across ALL phases
    name_lower = txn['Company Name'].lower()
    if any(fs in name_lower for fs in FUNCTIONAL_SUFFIXES):
        continue  # Skip Advisors/Partners/etc even in Phase 3
    
    name_normalized = normalize_name(txn['Company Name'], target_core)
    target_normalized = normalize_target(target_core)
    name_score = fuzzy_similarity(name_normalized, target_normalized)
    
    # Check account proximity to any target account
    account_scores = [levenshtein_distance(txn['Account Number'], acc) 
                      for acc in target_accounts]
    min_account_distance = min(account_scores) if account_scores else float('inf')
    
    # Tier 1: Strong name match (already handled in Phase 1)
    if name_score >= HIGH_THRESHOLD:
        matched_indices.add(i)
    # Tier 2: Exact account + weak name (already handled in Phase 2)
    elif min_account_distance == 0 and name_score >= 0.5:
        matched_indices.add(i)
    # Tier 3: Mutual reinforcement (CORRUPTED name + near-miss account)
    elif name_score >= MEDIUM_THRESHOLD and min_account_distance <= ACCOUNT_NEAR_THRESHOLD:
        matched_indices.add(i)
```

**Why this works for precision:**

Without mutual reinforcement, lowering the name threshold to catch corrupted names
creates false positives on distractors. Mutual reinforcement lets you lower the
threshold **safely** because account proximity acts as a second gate:

- `Northern Capital Group` (name score ~0.8) on unrelated account → ❌ fails account check
- `Nrth Wst Cptl Grp` (name score ~0.75) on `BUS-3000l` (distance 1 from `BUS-30001`) → ✅ both identifiers point to target

The conjunction of weak evidence from both identifiers is stronger than strong
evidence from one alone.

### Phase 4 — Near-Miss Exclusion (for data corruption)

**Critical rule:** Account numbers that differ by one character from a **well-established**
target account are almost certainly **data entry errors**, not legitimate separate accounts.

**When to apply Phase 4:**
- A row matches by name (Phase 1) → the name is VALID
- The account is a near-miss (Levenshtein ≤ 1) of a **well-established** target account
- A "well-established" account has **2+ rows** in the dataset

**Decision:** EXCLUDE the row (it's likely a corruption of the established account)

**Key insight:** The exclusion depends on whether the **target account** is well-established,
NOT on how many rows the near-miss account has. Even if the near-miss account has 3+ rows,
it's still likely a corruption if it's a near-miss of a well-established account.

**Example from v01:**
- BUS-41777: 5 rows → **well-established** target account
- BUS-41877: 1 row, near-miss of BUS-41777 → **EXCLUDED** (corruption)

Even if BUS-41877 had 3 rows, it would still be excluded because it's a near-miss of the
well-established BUS-41777.

**Implementation:**

```python
# Phase 4: Near-miss exclusion
from collections import defaultdict

# Count rows per account across ALL transactions (not just matched ones)
all_account_counts = defaultdict(int)
for txn in transactions:
    all_account_counts[txn['Account Number']] += 1

# Identify well-established target accounts (2+ rows)
well_established_accounts = {acc for acc, count in all_account_counts.items() 
                              if count >= 2 and acc in target_accounts}

final_indices = set()
for i in matched_indices:
    txn = transactions[i]
    account = txn['Account Number']
    
    # Check if this account is a near-miss of any well-established target account
    is_near_miss = False
    for target_acc in well_established_accounts:
        if account != target_acc:
            distance = levenshtein_distance(account, target_acc)
            if distance <= 1:
                is_near_miss = True
                break
    
    # Exclude if it's a near-miss of a well-established account
    if is_near_miss:
        continue  # Exclude (likely corruption)
    
    final_indices.add(i)
```

**Why this matters:**

The task says: "Account numbers are identifiers, not numbers: preserve them exactly
and **do not treat one-character-near account numbers as equal**."

This means: BUS-41877 and BUS-41777 are DIFFERENT accounts. But if BUS-41877 is a
near-miss of the well-established BUS-41777, it's almost certainly a data entry error,
not a legitimate separate account. Exclude it to maintain precision.

**The "well-established" criterion (2+ rows)** protects against false exclusions:
- If an account has only 1 row and is a near-miss of another 1-row account, both might
  be typos of a third account, or they might be legitimate separate accounts
- By requiring the TARGET account to have 2+ rows, we ensure it's genuinely established
  before excluding its near-misses

### Combining Results

Union of Phase 1, Phase 2, and Phase 3 matches, then apply Phase 4 near-miss exclusion. Sort by Date ascending.

## Output Format

- JSON array (no top-level wrapper object)
- One object per matching input row
- Keys: exactly the CSV column names (typically `Company Name`, `Account Number`,
  `Date`, `Amount`, `Transaction Type`, `Description`)
- All values are **strings preserved exactly** from the CSV
- Sorted by `Date` ascending

## Implementation Pattern

```python
import csv, json, re
from difflib import SequenceMatcher

# 1. Read CSV
transactions = list(csv.DictReader(open(input_path)))

# 2. Define target normalization
def normalize_name(name, target_core):
    """Normalize a company name for comparison with target."""
    n = name.lower().strip()
    # Expand abbreviations (target-specific, discovered from data)
    n = re.sub(r'n\.w\.?', 'north west', n)  # example
    n = re.sub(r'\bcap\.', 'capital', n)
    # Normalize spacing
    n = re.sub(r'northwest', 'north west', n)
    # Strip legal suffixes
    for suffix in [r'\bgroup\b', r'\bholdings\b', r'\bhldgs\.?\b',
                   r'\binc\.?\b', r'\bllc\.?\b', r'\bcorp\.?\b',
                   r'\bco\.?\b', r'\bltd\.?\b']:
        n = re.sub(suffix, '', n)
    n = re.sub(r'[^a-z\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def normalize_target(target_core):
    """Normalize the target name for comparison."""
    n = target_core.lower().strip()
    n = re.sub(r'[^a-z\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

# 3. Define functional-suffix exclusion list
FUNCTIONAL_SUFFIXES = ['advisors', 'advisory', 'partners', 'consulting', 'services']

def is_target_name(name, target_core):
    """Phase 1: Strong name match."""
    n = name.lower().strip()
    if any(fs in n for fs in FUNCTIONAL_SUFFIXES):
        return False
    normalized = normalize_name(name, target_core)
    target_normalized = normalize_target(target_core)
    return normalized == target_normalized

# 4. Fuzzy matching utilities
def fuzzy_similarity(s1, s2):
    """Return similarity ratio 0.0-1.0 between two strings."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, s1, s2).ratio()

def levenshtein_distance(s1, s2):
    """Compute edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

# 5. Phase 1: Strong name matching
target_accounts = set()
matched_indices = set()
target_normalized = normalize_target(target_core)

for i, txn in enumerate(transactions):
    if is_target_name(txn['Company Name'], target_core):
        target_accounts.add(txn['Account Number'])
        matched_indices.add(i)

# 6. Phase 2: Account propagation (exact match)
for i, txn in enumerate(transactions):
    if i not in matched_indices and txn['Account Number'] in target_accounts:
        matched_indices.add(i)

# 7. Phase 3: Mutual reinforcement (for corrupted identifiers)
HIGH_THRESHOLD = 0.95
MEDIUM_THRESHOLD = 0.7
ACCOUNT_NEAR_THRESHOLD = 2

for i, txn in enumerate(transactions):
    if i in matched_indices:
        continue
    
    # UNIVERSAL GATE: Functional-suffix exclusion applies across ALL phases
    name_lower = txn['Company Name'].lower()
    if any(fs in name_lower for fs in FUNCTIONAL_SUFFIXES):
        continue  # Skip Advisors/Partners/etc even in Phase 3
    
    name_normalized = normalize_name(txn['Company Name'], target_core)
    name_score = fuzzy_similarity(name_normalized, target_normalized)
    
    # Check account proximity to any target account
    account_distances = [levenshtein_distance(txn['Account Number'], acc) 
                         for acc in target_accounts]
    min_account_distance = min(account_distances) if account_distances else float('inf')
    
    # Tier 1: Strong name (already in Phase 1)
    if name_score >= HIGH_THRESHOLD:
        matched_indices.add(i)
    # Tier 2: Exact account + weak name (already in Phase 2)
    elif min_account_distance == 0 and name_score >= 0.5:
        matched_indices.add(i)
    # Tier 3: Mutual reinforcement
    elif name_score >= MEDIUM_THRESHOLD and min_account_distance <= ACCOUNT_NEAR_THRESHOLD:
        matched_indices.add(i)

# 8. Phase 4: Near-miss exclusion (for data corruption)
from collections import defaultdict

# Count rows per account across ALL transactions
all_account_counts = defaultdict(int)
for txn in transactions:
    all_account_counts[txn['Account Number']] += 1

# Identify well-established target accounts (2+ rows)
well_established_accounts = {acc for acc, count in all_account_counts.items() 
                              if count >= 2 and acc in target_accounts}

final_indices = set()
for i in matched_indices:
    txn = transactions[i]
    account = txn['Account Number']
    
    # Check if this account is a near-miss of any well-established target account
    is_near_miss = False
    for target_acc in well_established_accounts:
        if account != target_acc:
            distance = levenshtein_distance(account, target_acc)
            if distance <= 1:
                is_near_miss = True
                break
    
    # Exclude if it's a near-miss of a well-established account
    if is_near_miss:
        continue
    
    final_indices.add(i)

# 9. Output
filtered = sorted([transactions[i] for i in final_indices], key=lambda x: x['Date'])
json.dump(filtered, open(output_path, 'w'), indent=2)
```

## Key Design Decisions

### Suffix Taxonomy

| Suffix Type | Examples | Decision | Rationale |
|-------------|----------|----------|-----------|
| Legal/Structural | Group, Holdings, Hldgs, Inc, LLC | **Include** | Same entity, different corporate form |
| Functional | Advisors, Advisory, Partners | **Exclude** | Different business entity |

### Account Number Handling

- Preserve account numbers **exactly** as they appear in the CSV
- **Phase 2** uses only **exact** account number matches (never fuzzy)
- **Phase 3** uses near-miss account matching (Levenshtein ≤ 2) but ONLY for
  rows with CORRUPTED names that didn't match in Phase 1 — never for rows that
  already matched by name
- **Phase 4** EXCLUDES rows where the account is a near-miss (Levenshtein ≤ 1)
  of a **well-established** target account (2+ rows) — regardless of how many
  rows the near-miss account has
- The rule "do not treat one-character-near account numbers as equal" means:
  treat them as DIFFERENT accounts, and if one is a near-miss of a well-established
  target, it's likely a corruption → exclude it

### Abbreviation Handling

The abbreviation expansion must be tailored to the target entity. Common patterns:
- Initials with dots: `N.W.` → component words
- Truncated words: `Cap.` → `Capital`
- Merged words: `Northwest` → `North West`

For a new target entity, analyze the data to discover which abbreviations appear
and build the expansion rules from observed variants.

## Generalization Notes

This skill applies to any target entity name in a bank transaction dataset. The
specific abbreviation expansions and the set of functional suffixes to exclude
may vary by target and by domain, but the four-phase algorithm (name match →
account propagation → mutual reinforcement → near-miss exclusion) and the
legal-vs-functional suffix taxonomy are invariant.

When encountering a new target entity:
1. Scan the data for all company names containing any word from the target name
2. Classify each as same-entity (legal suffix) or different-entity (functional suffix)
3. Build abbreviation expansion rules from observed variants
4. Apply the four-phase algorithm
5. Tune thresholds based on observed corruption levels in the data
6. Pay special attention to near-miss accounts with single rows (Phase 4)

### Handling Variation Dimensions

**Company identity signal variation** — The target may appear under:
- Punctuation variations: `Cap.` vs `Capital`, `N.W.` vs `North West`
- Abbreviation variations: `Hldgs` vs `Holdings`, `Intl` vs `International`
- Spelling drift / typos: `Mounta5n` vs `Mountain`, `Insurce` vs `Insurance`
- Merged/split words: `Northwest` vs `North West`
- Legal-suffix changes: `Group` vs `Holdings` vs `Inc` vs `LLC`

For spelling drift beyond simple abbreviation expansion, use fuzzy string
matching (e.g., Levenshtein distance ≤ 2-3 on the normalized core) as a
supplement to exact normalization. The key is that the **core business name**
must be recognizable, even if individual characters are corrupted.

**Transaction membership inference** — Identity evidence propagates through:
- Account numbers established by clear name matches
- Multiple accounts belonging to the same company (discovered via Phase 1)
- Sparse anchor rows where only one identifier (name OR account) is clear

**Distractor entity confusability** — Precision requires excluding:
- Names that partially overlap the target (e.g., `Northern Light Energy` vs `North West Capital`)
- Functional-suffix entities (`Advisors`, `Partners`) that share the core name
- Account numbers that differ by 1-2 characters from target accounts
- Subsidiaries or partner entities with their own distinct names

The functional-suffix exclusion list and the exact-match account rule are the
primary precision mechanisms. Fuzzy name matching must be calibrated to avoid
false positives on confusable distractors.
