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
- Legal suffix differences (Group vs Advisors vs Holdings) indicate different entities

## Two-Pass Evidence Propagation Algorithm

### Pass 1: Anchor Establishment

Identify "anchor rows" — rows whose company name is a strong, recognizable variant of the target entity. These rows establish which account numbers belong to the target.

**Name matching criteria:**
1. **Normalize names**: lowercase, expand abbreviations (Cap. → Capital, N.W. → North West, NW → North West, Northwest → North West), remove punctuation
2. **Token-overlap fuzzy matching**: Split both the candidate and target names into word tokens. Compute the fraction of target tokens present in the candidate. Accept if overlap ≥ threshold (default 0.6). This handles spelling drift (typos in one word still allow partial match), unexpanded abbreviations, and word order variations.
3. **Extract base name and legal suffix**: The suffix is the last word(s) that form a recognized legal entity type (Group, Advisors, Advisory, Holdings, Partners, LLC, Inc, Ltd, etc.)
4. **Determine target entity's suffix**: Among all rows whose normalized name fuzzy-matches the target (token overlap ≥ threshold), the most common legal suffix is the target entity's suffix
5. **Strong match**: A row is an anchor if its normalized name fuzzy-matches the target (token overlap ≥ threshold) AND its suffix matches the target entity's established suffix

**Example:**
- Target: "North West Capital"
- Candidates: "North West Cap. Group" (suffix: group), "N.W. Capital Holdings" (suffix: holdings), "Northwest Capital Advisors" (suffix: advisors)
- Most common suffix: "group" → target entity's suffix
- Anchors: rows with "North West Capital" + "Group" suffix

### Pass 2: Account-Based Propagation

Once anchor rows establish the target's account numbers, include **all rows** on those accounts — even rows with shorter or more ambiguous company name aliases.

**Propagation rules:**
1. Collect all account numbers from anchor rows → established target accounts
2. Include every transaction whose account number is in the established set
3. Account numbers are **identifiers, not numbers**: preserve them exactly, never fuzzy-match (e.g., BUS-41777 ≠ BUS-41877)
4. If new anchor rows are discovered during propagation (strong name match on a new account), add that account to the established set and continue

## Critical Discrimination Rules

### Legal Suffix Discrimination

Different legal suffixes indicate different entities, even if the base name matches:
- "North West Capital **Group**" ≠ "North West Capital **Advisors**"
- "North West Capital **Group**" ≠ "N.W. Capital **Holdings**"
- "North West Capital **Group**" ≠ "Northwest Capital **Partners**"

The suffix is part of the entity's identity. A row with a different suffix is a different entity unless there's consistent evidence (same account) that it's the target.

### Strict Account Matching

Account numbers must match exactly:
- Never treat one-character-different accounts as equal
- BUS-41777 and BUS-41877 are different accounts
- Account numbers are strings, not numeric values

### Short Alias Inclusion

Once an account is established as belonging to the target, rows on that account with shorter aliases are included:
- If "North West Capital Group" on BUS-30001 establishes the account
- Then "North West Capital" (no suffix) on BUS-30001 is also included
- The account membership overrides the name variation

## Implementation Pattern

```python
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
    
    # Find candidate rows (fuzzy name match via token overlap)
    candidates = [t for t in transactions
                  if name_matches_target(normalize_name(t['Company Name']),
                                         target_normalized)]
    
    # Determine target entity's suffix (most common among candidates)
    suffix_counts = Counter(normalize_suffix(extract_suffix(t['Company Name'])[1])
                           for t in candidates)
    target_suffix = suffix_counts.most_common(1)[0][0]
    
    # Find anchor accounts (fuzzy name match AND suffix matches)
    anchor_accounts = set()
    for t in transactions:
        norm = normalize_name(t['Company Name'])
        _, suffix = extract_suffix(t['Company Name'])
        if name_matches_target(norm, target_normalized) and \
           normalize_suffix(suffix) == target_suffix:
            anchor_accounts.add(t['Account Number'])
    
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
- Discriminate by legal suffix (Group ≠ Advisors ≠ Holdings)
- Reject near-match account numbers (strict string equality)
- Exclude subsidiaries/partners unless account evidence links them
- Require consistent evidence, not superficial similarity
