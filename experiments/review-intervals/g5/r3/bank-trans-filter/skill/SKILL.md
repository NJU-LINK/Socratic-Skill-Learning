---
name: bank-trans-filter
description: >
  Filter bank transaction CSV files to retain only rows belonging to a target
  company, using multi-pass evidence-propagation entity resolution. Handles
  name variants (abbreviations, spelling drift, punctuation, legal suffixes),
  account-based propagation, and distractor rejection. Outputs a sorted JSON
  array with exact CSV values preserved as strings.
---

# Bank Transaction Filter

## Problem Family

Given a CSV of bank transactions and a target company name (extracted from the
task instruction), retain only rows belonging to that company. The challenge is
**entity resolution**: the same company appears under multiple name variants
and account numbers, while similar-looking but distinct entities must be
excluded.

## Core Algorithm: Multi-Pass Evidence Propagation

The solution requires multiple passes because no single criterion identifies
all target rows. Evidence discovered in early passes enables later passes.

### Step 1: Extract Target Name from Instruction

Parse the task instruction to identify the target company name. Common patterns:
- "Keep only the transactions that belong to {TARGET_NAME}"
- "Filter for {TARGET_NAME}"
- "Find all transactions for {TARGET_NAME}"

The target name is the full canonical name (e.g., "North West Capital").

### Step 2: Anchor Discovery (Fuzzy Name Matching)

For each row, determine if its `Company Name` is a variant of the target.

**Canonicalization** (applied to both company name and target name):
1. Lowercase
2. Remove common legal suffixes: LLC, Inc, Ltd, Corp, Co, Corporation,
   Incorporated, Group, Holdings, Hldgs, Company, Partners
3. Strip all punctuation (replace with spaces)
4. Collapse whitespace
5. Split into tokens

**Matching criteria** (a row is an anchor if ANY of these hold):

1. **Exact canonical match**: canonicalize(company_name) == canonicalize(target_name)

2. **Abbreviation expansion**: Single-letter tokens in the company name match
   the initials of target tokens. E.g., "N W Capital" matches "North West
   Capital" because N→North, W→West, Capital→Capital.

3. **Prefix/substring match**: One canonical form is a prefix of the other
   (handles cases where suffixes were stripped differently).

4. **Fuzzy match with edit distance**: If the canonical forms are similar but
   not identical, compute the normalized edit distance (Levenshtein distance
   divided by max length). If the distance is ≤ 0.2 (20% difference), treat
   as a variant. This handles typos ("Capitol" vs "Capital"), word merging
   ("Northwest" vs "North West"), and minor spelling drift.

   **Important**: Fuzzy matching should be applied AFTER checking for business
   descriptors. A name with a business descriptor (Advisors, Partners, etc.)
   should be rejected even if it fuzzy-matches the target.

**Entity boundary rule** — CRITICAL for precision:
- Names that add a **business descriptor** (Advisors, Advisory, Partners,
  Consulting, Management, Services, Adviser) are DIFFERENT entities, even if
  they share most words with the target.
- Names that only differ in abbreviations, spelling, punctuation, or generic
  corporate suffixes (Group, Holdings, Hldgs, LLC, Inc, Ltd) are the SAME entity.

**Test**: Would a human reading a bank statement consider these the same
company or different companies?

### Step 3: Account Establishment

Collect all `Account Number` values from anchor rows into an "established
accounts" set. These are now known to belong to the target entity.

### Step 4: Propagation

Scan ALL rows again. Any row whose `Account Number` exactly matches an
established account is included, even if its company name is shorter, more
abbreviated, or otherwise unrecognizable.

**Iteration**: After propagation, check if newly included rows have account
numbers not yet in the established set. If so, and if those rows have
reasonably-matching names, add their accounts to the established set and
repeat. Typically 2-3 rounds suffice.

**Conservative rule**: Only propagate FROM established accounts. A row with a
weak name match on a new account should not automatically establish that
account unless corroborating evidence exists.

### Step 5: Distractor Rejection (Precision Guard)

Review all included rows for false positives:

- **Near-miss account numbers**: "BUS-30001" vs "BUS-30002" are DIFFERENT
  accounts. Account numbers are string identifiers, compared with exact
  equality, never fuzzy-matched or treated as numbers.

- **Near-miss account rejection**: If an account number differs from an
  established target account by exactly one character AND appears in very few
  rows (weak evidence), reject it as likely identifier corruption. The company
  name alone is not sufficient when the account identifier is suspect. For
  example, if BUS-41777 is established with 5 rows and BUS-41877 (one char
  different) appears only once with a target name, reject BUS-41877.

- **Near-miss company names**: A company with a similar name but different
  business descriptor (e.g., "Target Capital Advisors" vs "Target Capital")
  is a different entity.

- **Shared accounts**: If an established target account also appears with a
  clearly non-target company name, investigate. This could indicate:
  (a) data error, (b) the account is genuinely shared (rare), or
  (c) your entity boundary is wrong.

### Step 6: Output Generation

- JSON array (no top-level wrapper object)
- One object per matching row
- Keys: `Company Name`, `Account Number`, `Date`, `Amount`,
  `Transaction Type`, `Description` (exact CSV column names)
- Sorted by `Date` ascending
- All values as strings, preserved exactly from CSV (including `$`, `-`, etc.)
- Do NOT parse Amount as numeric; do NOT reformat dates

## Key Principles

1. **Account numbers are identifiers, not numbers**: Compare with exact string
   equality. A one-character difference means a completely different account.

2. **Entity boundaries are semantic, not mechanical**: The question is whether
   the name refers to the same underlying company, not whether strings are
   similar. Business descriptors change entity identity; legal suffixes do not.

3. **Evidence propagation is essential**: You cannot identify all target rows
   by name matching alone. Some rows have short aliases (e.g., "NWC") that are
   only recognizable because other rows on the same account have full names.

4. **Preserve exact values**: Output must contain the exact strings from the
   CSV. Do not normalize, reformat, or correct typos in the output.

## Implementation Pattern

```python
import csv
import json
import re

def canonicalize(name):
    """Canonicalize company name for comparison."""
    s = name.lower().strip()
    # Remove legal suffixes
    for suffix in [' llc', ' inc', ' ltd', ' corp', ' co', ' corporation',
                   ' incorporated', ' group', ' holdings', ' hldgs', ' company']:
        if s.endswith(suffix):
            s = s[:-len(suffix)]
    # Strip punctuation, collapse whitespace
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def has_entity_descriptor(canon_name, target_canon):
    """Check if canon_name adds a business descriptor beyond the target.
    
    Only checks for descriptors in text REMAINING after removing target tokens.
    This prevents false rejections when the target name itself contains words
    that might match descriptor patterns.
    """
    # Remove target tokens from the name to see what's left
    remaining = canon_name
    for token in target_canon.split():
        remaining = remaining.replace(token, '', 1).strip()
    
    if not remaining:
        return False
    
    # Business descriptors indicate different entities
    # Note: Do NOT include generic corporate suffixes (holdings, group, etc.)
    descriptors = ['advisors', 'advisory', 'partners', 'consulting',
                   'management', 'services', 'adviser', 'ventures',
                   'associates', 'solutions']
    for desc in descriptors:
        if re.search(r'\b' + desc + r'\b', remaining):
            return True
    
    return False

def normalized_edit_distance(s1, s2):
    """Compute normalized Levenshtein distance (0.0 to 1.0)."""
    if not s1 or not s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    # Create distance matrix
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            dp[i][j] = min(dp[i-1][j] + 1,      # deletion
                          dp[i][j-1] + 1,      # insertion
                          dp[i-1][j-1] + cost) # substitution
    max_len = max(len1, len2)
    return dp[len1][len2] / max_len if max_len > 0 else 0.0

def is_variant(company_name, target_name):
    """Check if company_name is a variant of target_name."""
    canon = canonicalize(company_name)
    target_canon = canonicalize(target_name)
    
    # Check for business descriptors that indicate different entity
    if has_entity_descriptor(canon, target_canon):
        return False
    
    # Exact match
    if canon == target_canon:
        return True
    
    # Abbreviation expansion
    target_tokens = target_canon.split()
    canon_tokens = canon.split()
    if len(canon_tokens) <= len(target_tokens):
        match = True
        for i, ct in enumerate(canon_tokens):
            tt = target_tokens[i]
            if ct == tt:
                continue
            elif len(ct) == 1 and tt.startswith(ct):
                continue  # Abbreviation
            else:
                match = False
                break
        if match:
            return True
    
    # Prefix match
    if target_canon.startswith(canon) or canon.startswith(target_canon):
        return True
    
    # Fuzzy match with edit distance (handles typos, word merging, etc.)
    if normalized_edit_distance(canon, target_canon) <= 0.2:
        return True
    
    return False

def solve(csv_path, output_path, target_name):
    # Read CSV
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    
    # Pass 1: Anchor discovery
    anchors = set()
    for i, row in enumerate(rows):
        if is_variant(row['Company Name'], target_name):
            anchors.add(i)
    
    # Pass 2: Account establishment
    established_accounts = {rows[i]['Account Number'] for i in anchors}
    
    # Pass 2b: Near-miss account rejection
    from collections import Counter
    account_counts = Counter(rows[i]['Account Number'] for i in anchors)
    
    rejected_accounts = set()
    for acc in list(established_accounts):
        for other_acc in established_accounts:
            if acc == other_acc:
                continue
            if len(acc) == len(other_acc):
                diffs = sum(1 for a, b in zip(acc, other_acc) if a != b)
                if diffs == 1 and account_counts[acc] <= 1 and account_counts[other_acc] > 1:
                    rejected_accounts.add(acc)
    
    if rejected_accounts:
        established_accounts -= rejected_accounts
        anchors = {i for i in anchors if rows[i]['Account Number'] not in rejected_accounts}
    
    # Pass 3: Propagation (iterate until stable)
    for _ in range(5):
        prev = len(anchors)
        for i, row in enumerate(rows):
            if i not in anchors and row['Account Number'] in established_accounts:
                anchors.add(i)
        if len(anchors) == prev:
            break
    
    # Build output
    results = []
    for i in anchors:
        row = rows[i]
        results.append({
            'Company Name': row['Company Name'],
            'Account Number': row['Account Number'],
            'Date': row['Date'],
            'Amount': row['Amount'],
            'Transaction Type': row['Transaction Type'],
            'Description': row['Description'],
        })
    
    results.sort(key=lambda x: x['Date'])
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
```

## Variation Dimensions (from spec.yaml)

### company_identity_signal_variation
- **v01**: Target appears under abbreviations (N.W.), punctuation (Cap.),
  spelling variants, and legal suffix changes
- **Expected variations**: More severe spelling drift, partial-name matches,
  identifier corruption in company name or account number, cases where one
  identifier is trustworthy only after reconciling with the other

### transaction_membership_inference
- **v01**: Multiple accounts (BUS-30001, BUS-41777), propagation from
  established accounts to include rows with shorter aliases
- **Expected variations**: Multiple accounts per company, account reuse
  patterns, sparse anchor rows, datasets requiring extensive propagation

### distractor_entity_confusability
- **v01**: Non-target companies with business descriptors (Advisors, Partners,
  Advisory), near-miss account numbers (BUS-41877 vs BUS-41777, one char diff)
  that must be REJECTED as identifier corruption
- **Expected variations**: Non-target companies with partially overlapping
  names, accounts differing by one character, subsidiaries/partners that
  should remain excluded

## Common Pitfalls

1. **Over-matching**: Including rows with similar names but different business
   descriptors. Always check for Advisors, Partners, Advisory, etc.

2. **Under-matching**: Missing rows with short aliases that are only
   recognizable through account-based propagation.

3. **Fuzzy account matching**: Treating "BUS-30001" and "BUS-30002" as the
   same account. Account numbers are exact string identifiers.

4. **Near-miss account inclusion**: Including a row whose account number
   differs by one character from an established target account. When an
   account is a near-miss of a well-established account AND has weak evidence
   (e.g., only 1 row), it is likely identifier corruption and must be
   REJECTED, even if the company name is a valid target variant.

5. **Output formatting**: Parsing Amount as numeric, reformatting dates, or
   changing column names. Preserve exact CSV values.

6. **Hard-coded target names**: The solution must extract the target name from
   the task instruction, not assume it's always "North West Capital".

## Verification Checklist

- [ ] Target name extracted from instruction
- [ ] All name variants identified (abbreviations, spelling, suffixes)
- [ ] Business descriptors correctly excluded
- [ ] All target accounts established from anchors
- [ ] Propagation completed (iterate until stable)
- [ ] Account numbers compared with exact equality
- [ ] Output is JSON array with correct keys
- [ ] Sorted by Date ascending
- [ ] All values are strings preserved exactly from CSV
- [ ] No false positives (distractors excluded)
- [ ] No false negatives (all target rows included)
