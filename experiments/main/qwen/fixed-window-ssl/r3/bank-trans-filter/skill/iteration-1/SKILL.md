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
2. **Full name pattern**: Match the target name with any trailing suffix → `^North West Capital.*`
3. **Initial-based abbreviations**: Any prefix of words can become initials → `^N\.W\. Capital.*`, `^N\.W\.C\..*`
4. **Word-level abbreviations**: Common business-word truncations → "Capital" → "Cap.", "Holdings" → "Hldgs", "Group" → "Grp", "Corporation" → "Corp.", "International" → "Intl"
5. **Space/punctuation variants**: "NorthWest", "North-West", "N.W.", "NW"
6. **Legal-suffix variations**: The target may appear with different suffixes → Group, Holdings, Advisors, Advisory, Inc, LLC, Ltd, Corp

```python
def generate_seed_patterns(target_words):
    """Generate regex patterns from target company name words."""
    patterns = []
    # Full name with optional suffix
    full = r'\s+'.join(re.escape(w) for w in target_words)
    patterns.append(re.compile(r'^' + full + r'[\s\.,].*', re.I))
    patterns.append(re.compile(r'^' + full + r'$', re.I))
    # Initials for first N-1 words + last word(s)
    for i in range(1, len(target_words)):
        initials = r'\.\s*'.join(w[0] for w in target_words[:i]) + r'\.'
        remaining = r'\s+'.join(re.escape(w) for w in target_words[i:])
        patterns.append(re.compile(r'^' + initials + r'\s+' + remaining, re.I))
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
                patterns.append(re.compile(r'^' + pat + r'[\s\.,].*', re.I))
                patterns.append(re.compile(r'^' + pat + r'$', re.I))
    return patterns
```

**Critical**: If you miss a seed pattern, propagation never starts for that branch. Be generous with seed patterns — the propagation algorithm will filter out false positives via account-level evidence.

### Phase 2: Build Initial Account Set (Seed)

Scan all rows and collect account numbers from rows whose company name matches any seed pattern. These are the "seed accounts" — accounts with strong evidence of belonging to the target company.

```python
seed_accounts = set()
for row in rows:
    if any(pattern.match(row['Company Name']) for pattern in seed_patterns):
        seed_accounts.add(row['Account Number'])
```

### Phase 3: Iterative Evidence Propagation

Starting from the seed accounts, propagate evidence iteratively:

1. **Collect all rows on known target accounts**: Any row using an account in `target_accounts` belongs to the target, regardless of how abbreviated or corrupted the company name is.

2. **Discover new name variants**: Collect all company names from the rows found in step 1.

3. **Bootstrap new accounts**: If any discovered name variant appears on a new account (not yet in `target_accounts`), add that account to `target_accounts`.

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
    for row in rows:
        if (row['Company Name'] in target_names and 
            row['Account Number'] not in target_accounts):
            target_accounts.add(row['Account Number'])
            changed = True
```

**Why this works**: 
- A row like `"NWC Grp, BUS-30001"` would fail the seed patterns but is captured because BUS-30001 is already a known target account.
- A row like `"N.W. Capital Hldgs, BUS-99999"` with a corrupted account number is captured if it's the only name-recognizable anchor that links BUS-99999 to the target.
- Distractor entities (e.g., "Northwest Capital Advisors" on a different account) are excluded because their accounts never get bootstrapped by any seed row — there's no evidence bridge.

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
- Its company name matches a seed pattern, OR
- Its account number is in `target_accounts` (established by evidence propagation)

A row does NOT belong to the target just because:
- Its company name looks similar to the target (e.g., "Northwest" vs "North West")
- Its account number is similar to a target account (e.g., one character different)

### Distractor Exclusion

Entities that are separately named (advisors, partners, subsidiaries) must remain excluded unless there is consistent evidence that they are the target itself. The evidence propagation algorithm handles this naturally: if a distractor entity's account never gets bootstrapped by a seed row or propagated name, it remains excluded.

## Implementation Template

```python
import csv
import json
import re

def generate_seed_patterns(target_words):
    """Generate regex patterns from target company name words."""
    patterns = []
    full = r'\s+'.join(re.escape(w) for w in target_words)
    patterns.append(re.compile(r'^' + full + r'[\s\.,].*', re.I))
    patterns.append(re.compile(r'^' + full + r'$', re.I))
    for i in range(1, len(target_words)):
        initials = r'\.\s*'.join(w[0] for w in target_words[:i]) + r'\.'
        remaining = r'\s+'.join(re.escape(w) for w in target_words[i:])
        patterns.append(re.compile(r'^' + initials + r'\s+' + remaining, re.I))
    abbrev_map = {
        'capital': r'Cap(?:ital)?\.?',
        'holdings': r'Hldgs\.?',
        'group': r'Grp\.?',
        'corporation': r'Corp\.?',
        'international': r'Intl\.?',
    }
    for word, abbrev in abbrev_map.items():
        for idx, w in enumerate(target_words):
            if w.lower() == word:
                parts = [re.escape(tw) if i != idx else abbrev for i, tw in enumerate(target_words)]
                pat = r'\s+'.join(parts)
                patterns.append(re.compile(r'^' + pat + r'[\s\.,].*', re.I))
                patterns.append(re.compile(r'^' + pat + r'$', re.I))
    return patterns

def solve(target_company, input_csv, output_json):
    # Read CSV
    rows = []
    with open(input_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    
    # Phase 1: Generate seed patterns
    target_words = target_company.split()
    seed_patterns = generate_seed_patterns(target_words)
    
    # Phase 2: Build initial account set
    target_accounts = set()
    for row in rows:
        if any(pattern.match(row['Company Name']) for pattern in seed_patterns):
            target_accounts.add(row['Account Number'])
    
    # Phase 3: Iterative evidence propagation
    changed = True
    while changed:
        changed = False
        target_names = set()
        for row in rows:
            if row['Account Number'] in target_accounts:
                target_names.add(row['Company Name'])
        
        for row in rows:
            if (row['Company Name'] in target_names and 
                row['Account Number'] not in target_accounts):
                target_accounts.add(row['Account Number'])
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
- **Sparse anchors**: A single row with a recognizable name can bootstrap an entire account
- **Indirect evidence**: Names discovered on one account can establish membership on another account

### Distractor Entity Confusability

The algorithm achieves high precision by:
- Requiring evidence bridges (account overlap or name propagation) rather than superficial similarity
- Treating account numbers as exact identifiers, not fuzzy matches
- Excluding entities that never get bootstrapped by seed rows or propagated names

## Verification Checklist

Before finalizing output:
1. ✓ All rows on target accounts are included
2. ✓ All name variants discovered through propagation are captured
3. ✓ Output is sorted by Date ascending
4. ✓ Output is a JSON array with no top-level wrapper
5. ✓ Each object has exactly the required keys
6. ✓ All values are strings preserved exactly from CSV
7. ✓ Account numbers are preserved exactly (no numeric interpretation)
8. ✓ Distractor entities with no evidence bridge are excluded
