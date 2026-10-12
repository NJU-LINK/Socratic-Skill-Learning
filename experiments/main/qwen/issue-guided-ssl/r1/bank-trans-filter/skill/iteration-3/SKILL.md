---
name: bank-trans-filter
description: Entity resolution through evidence propagation for filtering bank transactions by target company, handling name variations, legal suffix discrimination, and account-based propagation
---

# Bank Transaction Filter: Entity Resolution via Evidence Propagation

## Core Problem

Filter bank transactions to include only those belonging to a target company, where:
- The target company appears under multiple name variants (abbreviations, punctuation, spelling drift)
- The target company may use multiple account numbers
- Similar-looking company names or account numbers may belong to different entities
- Legal suffix differences fall into two categories: structural suffixes (Group, Holdings) indicate the same entity with different legal forms, while functional suffixes (Advisors, Partners) indicate different business lines

## Two-Pass Evidence Propagation Algorithm

### Pass 1: Anchor Establishment

Identify "anchor rows" — rows whose company name is a strong, recognizable variant of the target entity. These rows establish which account numbers belong to the target.

**Name matching criteria:**
1. **Normalize names**: lowercase, expand abbreviations (Cap. → Capital, N.W. → North West, NW → North West, Northwest → North West), remove punctuation
2. **Token-overlap fuzzy matching**: Split both the candidate and target names into word tokens. Compute the fraction of target tokens present in the candidate. Accept if overlap ≥ threshold (default 0.6). This handles spelling drift (typos in one word still allow partial match), unexpanded abbreviations, and word order variations.
3. **Extract base name and legal suffix**: The suffix is the last word(s) that form a recognized legal entity type (Group, Advisors, Advisory, Holdings, Partners, LLC, Inc, Ltd, etc.)
4. **Suffix taxonomy — structural vs functional**: Legal suffixes fall into two categories:
   - **Structural suffixes** (included): Group, Holdings/Hldgs, LLC, Inc, Corp, Ltd, Co, Company. These indicate the same underlying company with a different legal form or corporate structure. When the base name matches the target, structural suffixes should all be included.
   - **Functional suffixes** (excluded): Advisors, Advisory, Partners. These indicate a different business function and thus a different entity. These are always excluded unless there's consistent account evidence they are the target.
5. **Strong match**: A row is an anchor if its normalized name fuzzy-matches the target (token overlap ≥ threshold) AND its suffix is NOT a functional/excluded suffix

**Example:**
- Target: "North West Capital"
- Candidates: "North West Cap. Group" (suffix: group, structural), "N.W. Capital Holdings" (suffix: holdings, structural), "Northwest Capital Advisors" (suffix: advisors, functional)
- Anchors: rows with structural suffixes (Group, Holdings) → accounts BUS-30001, BUS-41777
- Excluded: rows with functional suffixes (Advisors) → accounts BUS-41707, BUS-35001

### Pass 2: Account-Based Propagation

Once anchor rows establish the target's account numbers, include **all rows** on those accounts — even rows with shorter or more ambiguous company name aliases.

**Propagation rules:**
1. Collect all account numbers from anchor rows → established target accounts
2. Include every transaction whose account number is in the established set
3. Account numbers are **identifiers, not numbers**: preserve them exactly, never fuzzy-match (e.g., BUS-41777 ≠ BUS-41877)
4. If new anchor rows are discovered during propagation (strong name match on a new account), add that account to the established set and continue

## Critical Discrimination Rules

### Legal Suffix Discrimination

Legal suffixes fall into two categories:

**Structural suffixes** (same entity, different legal form):
- Group, Holdings/Hldgs, LLC, Inc, Corp, Ltd, Co, Company
- These indicate the same underlying company with a different corporate structure
- "North West Capital Group" and "N.W. Capital Holdings" are the same company — just different legal entities within the same corporate family

**Functional suffixes** (genuinely different business lines):
- Advisors, Advisory, Partners
- These indicate a different business function and thus a different entity
- "North West Capital Advisors" is a different business line than "North West Capital Group"
- The task explicitly warns: *"Advisors, partners, or other separately named entities must remain excluded unless the rows provide consistent evidence that they are the target itself."*

### Strict Account Matching

Account numbers must match exactly:
- Never treat one-character-different accounts as equal
- BUS-41777 and BUS-41877 are different accounts (one digit differs: 41**7**77 vs 41**8**77)
- Account numbers are strings, not numeric values
- When establishing anchor accounts, exclude accounts that are one-character-near matches from already-established accounts to prevent near-miss inclusions

### Short Alias Inclusion

Once an account is established as belonging to the target, rows on that account with shorter aliases are included:
- If "North West Capital Group" on BUS-30001 establishes the account
- Then "North West Capital" (no suffix) on BUS-30001 is also included
- The account membership overrides the name variation

## Implementation Pattern

```python
EXCLUDED_SUFFIXES = {'advisors', 'advisory', 'partners'}

def is_near_match_account(acc1, acc2):
    """Check if two account numbers differ by exactly one character."""
    if len(acc1) != len(acc2):
        return False
    return sum(1 for a, b in zip(acc1, acc2) if a != b) == 1

def name_matches_target(candidate_norm, target_norm, threshold=0.6):
    """Token-overlap fuzzy matching."""
    target_tokens = set(target_norm.split())
    candidate_tokens = set(candidate_norm.split())
    if not target_tokens:
        return False
    overlap = len(target_tokens & candidate_tokens)
    return (overlap / len(target_tokens)) >= threshold

def solve(input_csv, output_json, target_company):
    # Read transactions
    transactions = read_csv(input_csv)
    
    # Normalize target name
    target_normalized = normalize_name(target_company)
    
    # Find anchor accounts using exclusion-based suffix discrimination
    anchor_accounts = set()
    for t in transactions:
        norm = normalize_name(t['Company Name'])
        _, suffix = extract_suffix(t['Company Name'])
        norm_suffix = normalize_suffix(suffix)
        account_num = t['Account Number']
        
        # Anchor if: fuzzy name match AND suffix NOT excluded AND not near-match
        if name_matches_target(norm, target_normalized):
            if norm_suffix not in EXCLUDED_SUFFIXES:
                is_near = any(is_near_match_account(account_num, est) 
                             for est in anchor_accounts)
                if not is_near:
                    anchor_accounts.add(account_num)
    
    # Propagate: include all rows on established accounts
    matched = [t for t in transactions if t['Account Number'] in anchor_accounts]
    
    # Sort by date and write output
    matched.sort(key=lambda x: x['Date'])
    write_json(output_json, matched)
```

## Output Format

- JSON array (no top-level wrapper)
- One object per matching row
- Keys: `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`
- Sorted by `Date` ascending
- All values preserved exactly as strings from the CSV

## Variation Handling

### company_identity_signal_variation
- Handle severe spelling drift via fuzzy normalization
- Handle abbreviations (Cap., N.W., NW)
- Handle legal-suffix changes as entity boundaries
- Handle partial-name matches when combined with account evidence

### transaction_membership_inference
- Propagate identity through accounts (two-pass algorithm)
- Handle multiple accounts per company
- Handle sparse anchor rows that establish membership indirectly
- Iterate to fixed-point if new accounts are discovered

### distractor_entity_confusability
- Discriminate by suffix type: structural (Group, Holdings) included, functional (Advisors, Partners) excluded
- Reject near-match account numbers (strict string equality, one-character-near exclusion)
- Exclude subsidiaries/partners unless account evidence links them
- Require consistent evidence, not superficial similarity
