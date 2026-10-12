---
name: bank-trans-filter
description: Filter bank transactions to extract only those belonging to a target company, handling entity resolution across name variants, abbreviations, legal-suffix changes, and account number variations while excluding separate entities and near-matches.
---

# Bank Transaction Filter

## Task Overview

Given a CSV file of bank transactions and a target company name (from the task instructions), extract only the transactions belonging to that target company. The target company may appear under multiple name variants, and identity must be inferred from evidence across the entire dataset.

## Core Principle: Legal Suffixes vs. Functional Descriptors

The central distinction in entity resolution for company names:

- **Legal-entity suffixes** (Group, Holdings, Corp, Inc, Ltd, LLC, Co, PLC) describe a company's *legal form*. They are regularly used interchangeably for the same entity across different filings, bank accounts, and jurisdictions. "North West Capital Group" and "N.W. Capital Holdings" are the same company in different legal guises.
- **Functional business descriptors** (Advisors, Advisory, Partners, Consulting, Services, Trading, Management) describe a *line of business or role*. They typically indicate a distinct legal entity in a corporate family. "North West Capital Advisors" is a separate advisory firm, not the target.

This distinction drives the include/exclude decision throughout the algorithm.

## Algorithm

### Step 1: Parse input and build evidence structures

Read the CSV. Build:
- `company_names`: set of all distinct company names
- `account_to_names`: mapping from account number → set of company names seen on that account
- `name_to_accounts`: mapping from company name → set of account numbers seen with that name
- `all_rows`: list of all row dicts

### Step 2: Extract the target's core identity terms

From the target company name given in the instructions (e.g., "North West Capital"):

1. **Data-driven abbreviation expansion**: Scan the dataset for abbreviation patterns:
   - **Initials with periods**: Find patterns like `N.W.` — these are typically initials for multi-word names. To expand, look for dataset company names where the initial letters match. E.g., if "N.W." appears and "North West" also appears in the dataset, map N.W. → North West.
   - **Truncated words ending in period**: Find patterns like "Cap.", "Hldgs.", "Corp." — expand by finding longer words in the dataset vocabulary that share the same prefix. E.g., "Cap." → "Capital" if "Capital" appears elsewhere.
   - Build an abbreviation dictionary from these dataset-internal signals.

2. **Normalize the target name**:
   - Apply abbreviation expansions from step 1
   - Split compound words that the target uses in split form (e.g., if target says "North West", ensure "Northwest" in the dataset maps to the same tokens)
   - Remove punctuation and normalize whitespace
   - Lowercase everything

3. **Extract core terms**: The remaining words after normalization are the target's core identity terms. Example: "North West Capital" → `{"north", "west", "capital"}`.

### Step 3: Classify each company name

For each distinct company name in the dataset:

1. **Normalize** it using the same procedure (abbreviation expansion, compound splitting, punctuation removal, lowercase).

2. **Check core-term containment**: Does the normalized name contain ALL of the target's core terms?
   - **Critical**: Require `target_core ⊆ candidate_words` (candidate must contain every target term). Do NOT accept partial overlap — a company named just "Capital" or "Capital Group" shares one word but is not the target.
   - If the candidate does NOT contain all core terms → not a name match; skip to account-based classification later.

3. **Classify the non-core modifiers** (words in candidate that are NOT in target_core):
   - If all non-core words are **legal-entity suffixes** (or there are no non-core words) → **alias** of the target → include
   - If any non-core word is a **functional business descriptor** → **separate entity** → exclude
   - If ambiguous (e.g., "Services" could be legal or functional) → defer to account-number evidence (Step 4)

### Step 4: Account-number propagation

After name-based classification:

1. **Collect candidate target accounts**: For each name classified as an alias, collect all its account numbers as candidates.

2. **Detect near-account conflicts**: For each candidate account, check if it's a "near account" (one character different) from another candidate account. If two accounts differ by exactly one character, they are in conflict.

3. **Resolve conflicts by evidence strength**: When two accounts are in conflict:
   - Count how many recognized aliases appear on each account
   - The account with MORE recognized aliases is the "established" target account
   - The account with FEWER recognized aliases is a "near-account distractor" and must be EXCLUDED
   - If both accounts have the same number of aliases, apply additional heuristics in order:
     1. Prefer the account with MORE total rows (more activity = more likely legitimate)
     2. If still tied, prefer the account that appears first chronologically (earliest date)
     3. If still tied (very rare), keep both

4. **Build confirmed_accounts**: After resolving conflicts, only include the "established" accounts in `confirmed_accounts`. Near-account distractors are excluded.

5. **Propagate to unclassified names**: For each account in `confirmed_accounts`, check if any rows on that account have a company name not yet classified. If so, include those names as aliases (the shared account is strong evidence of same entity).

   **CRITICAL**: Do NOT override prior exclusion decisions from Step 3. If a name was classified as a separate entity (e.g., "North West Capital Advisors"), it must remain excluded even if it appears on a confirmed target account. A shared account alone is not sufficient evidence to override the functional-descriptor exclusion.

   ```python
   for acct in confirmed_accounts:
       for name in account_to_names[acct]:
           if name not in separate_entities:  # respect prior exclusion
               target_aliases.add(name)
   ```

6. **Handle typos in account numbers**: If an account number differs by exactly one character from a confirmed target account AND the company name on that account is a plausible name variant (normalized core terms overlap significantly), treat it as a typo-corrupted version of the target account. Include those rows.
   - **Caution**: Only do this when the name evidence is strong. One-character-different accounts with completely unrelated names are separate entities, not typos.
   - **Important**: This is different from the near-account conflict resolution in step 3. Here we're looking for accounts that are typos of CONFIRMED accounts (after conflict resolution), not conflicts between candidate accounts.

### Step 5: Filter and output

1. **Include** every row where the **account number** is in `confirmed_accounts`.
   - Note: Do NOT include rows just because the company name is a recognized alias. The account number must be confirmed.
   - This ensures that near-account distractors (e.g., BUS-41877) are excluded even if they have a recognized alias name.

2. **Output format**:
   - JSON array (no top-level wrapper object)
   - One object per matching input row
   - Keys: `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`
   - Sorted by `Date` ascending
   - All values as strings, preserved exactly from the CSV (do not parse amounts as numbers, do not modify account numbers)

## Implementation Pattern

```python
import csv
import json
import re
from datetime import datetime
from collections import defaultdict

# ── Step 1: Parse input ──────────────────────────────────────────────
all_rows = []
company_names = set()
account_to_names = defaultdict(set)
name_to_accounts = defaultdict(set)

with open('input.csv', 'r') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        all_rows.append(row)
        name = row['Company Name']
        acct = row['Account Number']
        company_names.add(name)
        account_to_names[acct].add(name)
        name_to_accounts[name].add(acct)

# ── Step 2: Data-driven abbreviation expansion ──────────────────────
# Build vocabulary of all words appearing in company names
all_words_in_names = set()
for name in company_names:
    for word in re.findall(r'[A-Za-z]+', name):
        all_words_in_names.add(word.lower())

# Find initials patterns (e.g., "N.W.") and expand using dataset vocabulary
def find_initial_expansions(initials, vocabulary):
    """For initials like 'N.W.', find sequences of words matching the initials."""
    letters = [c.lower() for c in initials if c.isalpha()]
    # Find all words starting with each letter
    candidates_per_letter = []
    for letter in letters:
        matches = [w for w in vocabulary if w.startswith(letter) and len(w) > 2]
        candidates_per_letter.append(matches)
    
    # Return as list of possible expansions (each is a list of words for that letter)
    return candidates_per_letter

# Find truncated-word patterns (e.g., "Cap." → "Capital")
def find_truncation_expansions(truncated, vocabulary):
    """Given 'Cap.', find vocabulary words starting with 'cap'."""
    stem = truncated.rstrip('.').lower()
    return [w for w in vocabulary if w.startswith(stem) and len(w) > len(stem)]

# Build abbreviation mapping from dataset evidence
abbrev_map = {}
for name in company_names:
    # Find initials: sequences of single letters with periods
    for match in re.finditer(r'\b((?:[A-Z]\.)+(?:[A-Z]\.)?)', name):
        initials = match.group(1)
        expansions = find_initial_expansions(initials, all_words_in_names)
        abbrev_map[initials] = ('initials', expansions)
    
    # Find truncated words: short words ending in period
    for match in re.finditer(r'\b([A-Za-z]{2,5}\.)', name):
        truncated = match.group(1)
        expansions = find_truncation_expansions(truncated, all_words_in_names)
        abbrev_map[truncated] = ('truncated', expansions)

# ── Normalization function ───────────────────────────────────────────
LEGAL_SUFFIXES = {'group', 'holdings', 'corp', 'inc', 'ltd', 'llc', 'co', 'plc',
                  'company', 'corporation', 'incorporated'}
FUNCTIONAL_DESCRIPTORS = {'advisors', 'advisory', 'partners', 'consulting', 
                          'services', 'trading', 'management', 'associates',
                          'ventures', 'solutions', 'technologies'}

def normalize_name(name, target_name):
    """
    Normalize a company name for comparison against target.
    Uses dataset-internal evidence for abbreviation expansion.
    """
    # Apply abbreviation expansions from dataset
    for abbrev, (abbrev_type, expansions) in abbrev_map.items():
        if abbrev in name:
            target_words = set(re.findall(r'[A-Za-z]+', target_name.lower()))
            
            if abbrev_type == 'initials':
                # For initials, find the best matching sequence
                # Each element in expansions is a list of words starting with that letter
                # Try to find a sequence that matches target words
                best_expansion = []
                for word_candidates in expansions:
                    best_word = None
                    for word in word_candidates:
                        if word in target_words:
                            best_word = word
                            break
                    if best_word:
                        best_expansion.append(best_word)
                
                if best_expansion:
                    replacement = ' '.join(best_expansion)
                    name = name.replace(abbrev, replacement)
            
            elif abbrev_type == 'truncated':
                # For truncated words, find the best matching expansion
                best = None
                for exp in expansions:
                    if exp in target_words:
                        best = exp
                        break
                if best:
                    name = name.replace(abbrev, best)
    
    # Handle compound word splitting: if target uses "North West" (two words),
    # treat "Northwest" as equivalent
    target_lower = target_name.lower()
    # Find multi-word sequences in target that might appear as compounds
    target_words_list = re.findall(r'[a-z]+', target_lower)
    for i in range(len(target_words_list) - 1):
        compound = target_words_list[i] + target_words_list[i+1]
        split_form = target_words_list[i] + ' ' + target_words_list[i+1]
        # If the compound appears in the name, split it
        if compound in name.lower():
            name = re.sub(rf'\b{compound}\b', split_form, name, flags=re.IGNORECASE)
    
    # Remove all punctuation and normalize whitespace
    name = re.sub(r'[^a-zA-Z0-9\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name.lower()

def strip_legal_suffixes(normalized_name):
    """Remove legal-entity suffixes from a normalized name."""
    words = normalized_name.split()
    return ' '.join(w for w in words if w not in LEGAL_SUFFIXES)

# ── Step 3: Classify each company name ───────────────────────────────
# Extract target name from task instructions (not hardcoded)
# For v01: "North West Capital"
# For other variants: parse from the instruction text
TARGET_NAME = "North West Capital"  # ← extract from task instructions

target_normalized = normalize_name(TARGET_NAME, TARGET_NAME)
target_core = set(strip_legal_suffixes(target_normalized).split())

target_aliases = set()
separate_entities = set()

for name in company_names:
    normalized = normalize_name(name, TARGET_NAME)
    words = set(normalized.split())
    
    # CRITICAL: candidate must contain ALL target core terms
    if not target_core.issubset(words):
        continue  # not a name match; may be caught by account propagation
    
    # Find non-core modifiers
    non_core = words - target_core
    
    # Classify modifiers
    has_functional = bool(non_core & FUNCTIONAL_DESCRIPTORS)
    has_legal = bool(non_core & LEGAL_SUFFIXES)
    
    if has_functional and not has_legal:
        separate_entities.add(name)
    else:
        # Legal suffixes only, or no modifiers → alias
        target_aliases.add(name)

# ── Step 4: Account-number propagation ───────────────────────────────
# Collect candidate accounts from recognized aliases
candidate_accounts = set()
for name in target_aliases:
    candidate_accounts.update(name_to_accounts[name])

# Detect near-account conflicts: accounts that differ by exactly one character
def find_near_account_conflicts(accounts):
    """Find pairs of accounts that differ by exactly one character."""
    conflicts = []
    account_list = list(accounts)
    for i in range(len(account_list)):
        for j in range(i + 1, len(account_list)):
            acct1, acct2 = account_list[i], account_list[j]
            if len(acct1) == len(acct2):
                diffs = sum(1 for a, b in zip(acct1, acct2) if a != b)
                if diffs == 1:
                    conflicts.append((acct1, acct2))
    return conflicts

# Resolve conflicts by evidence strength
confirmed_accounts = set(candidate_accounts)
conflicts = find_near_account_conflicts(candidate_accounts)

for acct1, acct2 in conflicts:
    # Count how many recognized aliases appear on each account
    aliases_on_acct1 = len([n for n in account_to_names[acct1] if n in target_aliases])
    aliases_on_acct2 = len([n for n in account_to_names[acct2] if n in target_aliases])
    
    # The account with MORE aliases is the established target account
    # The account with FEWER aliases is a near-account distractor
    if aliases_on_acct1 > aliases_on_acct2:
        confirmed_accounts.discard(acct2)
    elif aliases_on_acct2 > aliases_on_acct1:
        confirmed_accounts.discard(acct1)
    else:
        # Tie: use additional heuristics
        # Prefer the account with MORE total rows (more activity = more likely legitimate)
        rows_on_acct1 = len([r for r in all_rows if r['Account Number'] == acct1])
        rows_on_acct2 = len([r for r in all_rows if r['Account Number'] == acct2])
        if rows_on_acct1 > rows_on_acct2:
            confirmed_accounts.discard(acct2)
        elif rows_on_acct2 > rows_on_acct1:
            confirmed_accounts.discard(acct1)
        else:
            # Still tied: prefer the account that appears first chronologically
            dates_acct1 = [r['Date'] for r in all_rows if r['Account Number'] == acct1]
            dates_acct2 = [r['Date'] for r in all_rows if r['Account Number'] == acct2]
            if dates_acct1 and dates_acct2:
                if min(dates_acct1) < min(dates_acct2):
                    confirmed_accounts.discard(acct2)
                else:
                    confirmed_accounts.discard(acct1)
            # If still tied, keep both (very rare edge case)

# Propagate: any UNCLASSIFIED name appearing on a confirmed account is also an alias
# CRITICAL: Don't override prior exclusion decisions from Step 3
for acct in confirmed_accounts:
    for name in account_to_names[acct]:
        if name not in separate_entities:  # respect prior exclusion
            target_aliases.add(name)

# ── Step 5: Filter and output ────────────────────────────────────────
# Only include rows where the account number is in confirmed_accounts
# (not just where the company name is a recognized alias)
matching_rows = [row for row in all_rows if row['Account Number'] in confirmed_accounts]
matching_rows.sort(key=lambda x: datetime.strptime(x['Date'], '%Y-%m-%d'))

with open('output.json', 'w') as f:
    json.dump(matching_rows, f, indent=2)
```

## Decision Framework

When uncertain whether a variant is an alias or separate entity:

1. **Name-based evidence**:
   - Contains ALL target core terms + only legal suffixes → **include**
   - Contains ALL target core terms + functional descriptor → **exclude**
   - Contains only SOME target core terms → **insufficient name evidence**; need account overlap

2. **Account-based evidence**:
   - Same account number as confirmed target → **include** (strong evidence)
   - One-character-different account + plausible name → **likely typo**; include with caution
   - One-character-different account + unrelated name → **separate entity**; exclude

3. **Conservative principle**:
   - When in doubt, exclude rather than include
   - False positives (including non-target) are worse than false negatives
   - Account propagation is the safety net for names that are too short/abbreviated to match by name alone

## Common Pitfalls

1. **Partial overlap trap**: A company named "Capital Group" shares one word with "North West Capital" but is NOT the target. Always require ALL core terms to match.
2. **Functional descriptor blindness**: "Advisors", "Partners", "Associates" indicate separate entities even when the rest of the name matches.
3. **Near-account distractors**: When an alias appears on multiple accounts, and one account is one character different from another (e.g., BUS-41777 vs BUS-41877), the account with FEWER recognized aliases is a distractor and must be excluded. Account numbers are identifiers, not numbers — one-character differences matter.
4. **Over-propagation**: Don't extend identity from a weakly-matched name to all its accounts. Only propagate from confirmed aliases.
5. **Propagation overriding exclusion**: If Step 3 classifies a name as a separate entity (e.g., "Advisors"), Step 4 must NOT re-include it just because it shares an account with the target. Classification decisions have higher authority than propagation.
6. **Hardcoded abbreviations**: Don't maintain a fixed dictionary of abbreviations. Derive them from the dataset's own vocabulary.

## Verification Checklist

- [ ] Target name extracted from task instructions (not hardcoded)
- [ ] Abbreviation expansion is data-driven from dataset vocabulary
- [ ] Name matching requires ALL target core terms (not partial overlap)
- [ ] Legal suffixes treated as interchangeable; functional descriptors as separate entities
- [ ] Near-account conflicts detected and resolved (accounts differing by 1 char)
- [ ] Account with fewer recognized aliases excluded as near-account distractor
- [ ] Account propagation catches short/unrecognizable aliases on confirmed accounts
- [ ] Account propagation does NOT override prior exclusion decisions (Step 3 > Step 4)
- [ ] Account numbers preserved exactly as strings (no numeric parsing)
- [ ] Output sorted by date ascending
- [ ] Output is JSON array with correct keys, no wrapper object
- [ ] All values are strings preserved exactly from CSV
