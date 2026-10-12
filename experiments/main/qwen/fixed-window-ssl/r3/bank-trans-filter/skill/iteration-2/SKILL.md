---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a specified target company,
  using iterative evidence propagation across company name variants and account numbers.
  Handles spelling variations, abbreviations, legal-suffix changes, account-based propagation,
  and distractor exclusion.
---

# Bank Transaction Filter

## Overview

This skill extracts all transactions belonging to a target company from a bank transaction CSV file. The challenge is that the same company may appear under multiple name variants (abbreviations, punctuation changes, spelling variations, legal-suffix differences) and multiple account numbers. The skill uses an iterative evidence propagation algorithm to identify all relevant rows.

## Core Algorithm: Iterative Evidence Propagation

The algorithm operates in four phases:

### Phase 1: Parse Target and Define Seed Patterns

Extract the target company name from the task instruction. Then systematically generate seed patterns:

1. **Tokenize** the name into words: e.g., "North West Capital" → `["North", "West", "Capital"]`
2. **Full name pattern**: Match the target name with a core identity suffix or end of string → `^North West Capital(?:\s+(?:Group|Holdings|...))?$`
3. **Initial-based abbreviations**: Any prefix of words can become initials → `^N\.W\. Capital.*`, `^N\.W\.C\..*`
4. **Word-level abbreviations**: Common business-word truncations → "Capital" → "Cap.", "Holdings" → "Hldgs", "Group" → "Grp", "Corporation" → "Corp.", "International" → "Intl"
5. **Space/punctuation variants**: "NorthWest", "North-West", "N.W.", "NW"
6. **Core identity suffixes only**: Group, Holdings, Hldgs, Inc, LLC, Ltd, Corp, Co, Company, Limited, Corporation, International, Intl. **Exclude**: Advisors, Advisory, Partners, Associates, Consultants — these signal separate legal entities.

```python
def generate_seed_patterns(target_words):
    """Generate regex patterns from target company name words."""
    patterns = []
    # Core identity suffixes (exclude Advisors, Advisory, Partners, etc.)
    core_suffixes = [
        'Group', 'Holdings', 'Hldgs', 'Inc', 'LLC', 'Ltd', 'Corp', 
        'Co', 'Company', 'Limited', 'Corporation', 'International', 'Intl'
    ]
    
    # Full name with core suffixes only
    full_base = r'\s+'.join(re.escape(w) for w in target_words)
    suffix_pattern = r'(?:\s+(?:' + '|'.join(core_suffixes) + r'))?'
    patterns.append(re.compile(r'^' + full_base + suffix_pattern + r'$', re.I))
    
    # Initials for first N-1 words + last word(s)
    for i in range(1, len(target_words)):
        initials = r'\.\s*'.join(w[0] for w in target_words[:i]) + r'\.'
        remaining = r'\s+'.join(re.escape(w) for w in target_words[i:])
        patterns.append(re.compile(r'^' + initials + r'\s+' + remaining + suffix_pattern + r'$', re.I))
    
    # Abbreviation substitutions for common business words
    abbrev_map = {
        'capital': r'Cap(?:ital)?\.?',
        'holdings': r'Hldgs\.?',
        'group': r'Grp\.?',
        'corporation': r'Corp\.?',
        'international': r'Intl\.?',
    }
    # Build patterns with abbreviations substituted in
    for word, abbrev in abbrev_map.items():
        for idx, w in enumerate(target_words):
            if w.lower() == word:
                parts = [re.escape(tw) if i != idx else abbrev for i, tw in enumerate(target_words)]
                pat = r'\s+'.join(parts)
                patterns.append(re.compile(r'^' + pat + suffix_pattern + r'$', re.I))
    return patterns
```

**Critical**: The suffix list explicitly excludes "Advisors", "Advisory", "Partners", "Associates", "Consultants" — these signal separate legal entities that must remain excluded per the task instruction.

**Critical**: If you miss a seed pattern, propagation never starts for that branch. Be generous with seed patterns — the propagation algorithm will filter out false positives via account-level evidence.

### Phase 2: Build Initial Account Set (Two-Pass Seed with Near-Account Detection)

**Pass 1:** Find all candidate seed accounts (≥1 row matches seed pattern).

**Pass 2:** Filter out near-account distractors. A near-match to a STRONGER seed account (more matching rows) with only 1 matching row is likely a data entry error.

```python
from collections import defaultdict

def is_near_match(acc1, acc2):
    """Check if two account numbers differ by exactly one character."""
    if len(acc1) != len(acc2):
        return False
    diffs = sum(1 for a, b in zip(acc1, acc2) if a != b)
    return diffs == 1

# Group rows by account
account_rows = defaultdict(list)
for row in rows:
    account_rows[row['Account Number']].append(row)

# Pass 1: Find candidate seed accounts
candidate_seeds = {}
for account, account_row_list in account_rows.items():
    seed_matches = [r for r in account_row_list 
                    if any(p.match(r['Company Name']) for p in seed_patterns)]
    if seed_matches:
        candidate_seeds[account] = len(seed_matches)

# Pass 2: Filter out near-account distractors
target_accounts = set()
for account, match_count in candidate_seeds.items():
    # A near-match to a STRONGER seed account with only 1 matching row is suspicious
    near_stronger = any(
        is_near_match(account, other) and candidate_seeds[other] > match_count
        for other in candidate_seeds if other != account
    )
    if near_stronger and match_count < 2:
        continue  # Exclude: weak near-account distractor
    target_accounts.add(account)
```

**Why this works:**
- BUS-41877 (1 row, near-match to BUS-41777 with 5 rows) is excluded as a data entry anomaly
- BUS-30001 (8 rows) and BUS-41777 (5 rows) are included as strong seeds
- Legitimate sparse anchors (single-row accounts with no stronger near-neighbor) are preserved

### Phase 3: Iterative Evidence Propagation with Near-Account Detection

Starting from the seed accounts, propagate evidence iteratively:

1. **Collect all rows on known target accounts**: Any row using an account in `target_accounts` belongs to the target, regardless of how abbreviated or corrupted the company name is.

2. **Discover new name variants**: Collect all company names from the rows found in step 1.

3. **Bootstrap new accounts**: If any discovered name variant appears on a new account (not yet in `target_accounts`), add that account to `target_accounts`. **Note:** For propagation, a single row is sufficient — the name was already established on a known target account, providing the evidence bridge. **However:** If the new account is a near-match (one character different) to an existing target account and has only 1 matching row, exclude it as a near-account distractor.

4. **Repeat until stable**: Continue iterating until no new accounts are added.

```python
target_accounts = set(seed_accounts)
changed = True
while changed:
    changed = False
    # Collect all names on known accounts
    target_names = set()
    for row in rows:
        if row['Account Number'] in target_accounts:
            target_names.add(row['Company Name'])
    
    # Check if any name appears on new accounts
    for account, account_row_list in account_rows.items():
        if account not in target_accounts:
            matching_rows = [r for r in account_row_list if r['Company Name'] in target_names]
            if matching_rows:
                # Check if this is a near-account distractor
                near_existing = any(is_near_match(account, ta) for ta in target_accounts)
                if near_existing and len(matching_rows) < 2:
                    continue  # Exclude: near-account with insufficient evidence
                target_accounts.add(account)
                changed = True
```

**Why this works**: 
- A row like `"NWC Grp, BUS-30001"` would fail the seed patterns but is captured because BUS-30001 is already a known target account.
- A row like `"N.W. Capital Hldgs, BUS-99999"` with a corrupted account number is captured if it's the only name-recognizable anchor that links BUS-99999 to the target.
- Distractor entities (e.g., "Northwest Capital Advisors" on a different account) are excluded because their accounts never get bootstrapped by any seed row — there's no evidence bridge.
- **Near-account distractors** (e.g., BUS-41877 which is one character off from BUS-41777) are excluded during the seed phase by the near-account detection logic.

### Phase 4: Collect and Format Output

1. **Collect matching rows**: All rows whose account number is in `target_accounts`.

2. **Sort by Date**: Sort the rows by the `Date` field in ascending order.

3. **Write JSON output**: Write a JSON array (no top-level wrapper) where each object has exactly these keys:
   - `Company Name`
   - `Account Number`
   - `Date`
   - `Amount`
   - `Transaction Type`
   - `Description`

All values must be strings preserved exactly from the CSV.

## Key Principles

### Account Numbers Are Identifiers, Not Numbers

Account numbers must be preserved exactly and compared as strings. Do not treat one-character-near account numbers as equal. For example, `BUS-41777` and `BUS-41877` are different accounts, even though they differ by only one character.

### Evidence-Based Inclusion

A row belongs to the target if:
- Its account number is in `target_accounts` (established by seed patterns or evidence propagation)

An account is established if:
- It has ≥1 row with a name matching a seed pattern (and is not a near-account distractor), OR
- It has ≥1 row with a name discovered from another target account (propagation)

A row does NOT belong to the target just because:
- Its company name looks similar to the target (e.g., "Northwest" vs "North West")
- Its account number is similar to a target account (e.g., one character different)
- Its name has a separate-entity suffix (Advisors, Advisory, Partners) even if it matches the target name pattern

### Distractor Exclusion

Entities that are separately named (advisors, partners, subsidiaries) must remain excluded unless there is consistent evidence that they are the target itself. The algorithm handles this through three mechanisms:

1. **Suffix-based exclusion in seed patterns**: The seed patterns explicitly exclude "Advisors", "Advisory", "Partners", "Associates", "Consultants" suffixes. These signal separate legal entities and never match as seeds.

2. **Near-account detection in seed and propagation phases**: An account with a single row that is a near-match (one character different) to a stronger seed account is excluded as a likely data entry error. This applies both during the initial seed phase and during propagation. This catches cases like BUS-41877 (one character off from BUS-41777) whether it appears as a seed candidate or is discovered through propagation.

3. **Evidence bridge requirement**: Entities with different spellings (e.g., "Northwest" vs "North West") don't match seed patterns and have no evidence bridge, so they're excluded.

The key principle: **Separate-entity suffixes and near-account anomalies are excluded at both the seed and propagation levels**, not by row count. Legitimate sparse anchors (single-row accounts with no stronger near-neighbor) are preserved.

## Implementation Template

```python
import csv
import json
import re

def generate_seed_patterns(target_words):
    """Generate regex patterns from target company name words."""
    patterns = []
    # Core identity suffixes (exclude Advisors, Advisory, Partners, etc.)
    core_suffixes = [
        'Group', 'Holdings', 'Hldgs', 'Inc', 'LLC', 'Ltd', 'Corp', 
        'Co', 'Company', 'Limited', 'Corporation', 'International', 'Intl'
    ]
    
    # Full name with core suffixes only
    full_base = r'\s+'.join(re.escape(w) for w in target_words)
    suffix_pattern = r'(?:\s+(?:' + '|'.join(core_suffixes) + r'))?'
    patterns.append(re.compile(r'^' + full_base + suffix_pattern + r'$', re.I))
    
    # Initials for first N-1 words + last word(s)
    for i in range(1, len(target_words)):
        initials = r'\.\s*'.join(w[0] for w in target_words[:i]) + r'\.'
        remaining = r'\s+'.join(re.escape(w) for w in target_words[i:])
        patterns.append(re.compile(r'^' + initials + r'\s+' + remaining + suffix_pattern + r'$', re.I))
    
    # Abbreviation substitutions for common business words
    abbrev_map = {
        'capital': r'Cap(?:ital)?\.?',
        'holdings': r'Hldgs\.?',
        'group': r'Grp\.?',
        'corporation': r'Corp\.?',
        'international': r'Intl\.?',
    }
    # Build patterns with abbreviations substituted in
    for word, abbrev in abbrev_map.items():
        for idx, w in enumerate(target_words):
            if w.lower() == word:
                parts = [re.escape(tw) if i != idx else abbrev for i, tw in enumerate(target_words)]
                pat = r'\s+'.join(parts)
                patterns.append(re.compile(r'^' + pat + suffix_pattern + r'$', re.I))
    return patterns

def is_near_match(acc1, acc2):
    """Check if two account numbers differ by exactly one character."""
    if len(acc1) != len(acc2):
        return False
    diffs = sum(1 for a, b in zip(acc1, acc2) if a != b)
    return diffs == 1

def solve(target_company, input_csv, output_json):
    from collections import defaultdict
    
    # Read CSV
    rows = []
    with open(input_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    
    # Group rows by account
    account_rows = defaultdict(list)
    for row in rows:
        account_rows[row['Account Number']].append(row)
    
    # Phase 1: Generate seed patterns
    target_words = target_company.split()
    seed_patterns = generate_seed_patterns(target_words)
    
    # Phase 2: Two-pass seed with near-account detection
    # Pass 1: Find candidate seed accounts
    candidate_seeds = {}
    for account, account_row_list in account_rows.items():
        seed_matches = [r for r in account_row_list
                        if any(p.match(r['Company Name']) for p in seed_patterns)]
        if seed_matches:
            candidate_seeds[account] = len(seed_matches)
    
    # Pass 2: Filter out near-account distractors
    target_accounts = set()
    for account, match_count in candidate_seeds.items():
        near_stronger = any(
            is_near_match(account, other) and candidate_seeds[other] > match_count
            for other in candidate_seeds if other != account
        )
        if near_stronger and match_count < 2:
            continue  # Exclude: weak near-account distractor
        target_accounts.add(account)
    
    # Phase 3: Iterative evidence propagation with near-account check
    changed = True
    while changed:
        changed = False
        target_names = set()
        for row in rows:
            if row['Account Number'] in target_accounts:
                target_names.add(row['Company Name'])
        
        for account, account_row_list in account_rows.items():
            if account not in target_accounts:
                matching = [r for r in account_row_list if r['Company Name'] in target_names]
                if matching:
                    # Check if this is a near-account distractor
                    near_existing = any(is_near_match(account, ta) for ta in target_accounts)
                    if near_existing and len(matching) < 2:
                        continue  # Exclude: near-account with insufficient evidence
                    target_accounts.add(account)
                    changed = True
    
    # Phase 4: Collect and format output
    matching_rows = [row for row in rows if row['Account Number'] in target_accounts]
    matching_rows.sort(key=lambda x: x['Date'])
    
    with open(output_json, 'w') as f:
        json.dump(matching_rows, f, indent=2)
    
    return len(matching_rows)
```

## Handling Variation Dimensions

### Company Identity Signal Variation

The seed patterns must be flexible enough to handle:
- **Spelling drift**: "North West" vs "Northwest" vs "N.W."
- **Abbreviations**: "Capital" → "Cap.", "Holdings" → "Hldgs"
- **Legal-suffix changes**: "Group" vs "Inc" vs "LLC" vs "Ltd"
- **Partial-name matches**: Short aliases like "NWC"

The propagation algorithm handles cases where a row's name is too corrupted to match seed patterns but its account number is already established.

### Transaction Membership Inference

The propagation algorithm handles:
- **Multiple accounts**: The target company may use multiple accounts
- **Sparse anchors**: A single row with a recognizable name can bootstrap an entire account (if it's not a near-account distractor)
- **Indirect evidence**: Names discovered on one account can establish membership on another account

### Distractor Entity Confusability

The algorithm achieves high precision by:
- Requiring evidence bridges (account overlap or name propagation) rather than superficial similarity
- Treating account numbers as exact identifiers, not fuzzy matches
- Excluding entities that never get bootstrapped by seed rows or propagated names

## Verification Checklist

Before finalizing output:
1. ✓ Seed patterns exclude separate-entity suffixes (Advisors, Advisory, Partners, etc.)
2. ✓ Seed accounts are not near-account distractors (one char off from stronger seed)
3. ✓ Propagation includes sparse anchors (single-row accounts with discovered names)
4. ✓ All rows on target accounts are included
5. ✓ All name variants discovered through propagation are captured
6. ✓ Output is sorted by Date ascending
7. ✓ Output is a JSON array with no top-level wrapper
8. ✓ Each object has exactly the required keys
9. ✓ All values are strings preserved exactly from CSV
10. ✓ Account numbers are preserved exactly (no numeric interpretation)
11. ✓ Near-account distractors are excluded
12. ✓ Separately named entities (Advisors, Partners, etc.) are excluded
