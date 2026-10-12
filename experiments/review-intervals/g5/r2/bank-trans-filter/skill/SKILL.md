---
name: bank-trans-filter
description: >
  Filter bank transaction CSVs to extract only rows belonging to a named target
  entity, using connected-components evidence propagation across company-name
  variants and account-number identifiers. Handles spelling drift, abbreviations,
  legal-suffix changes, account-number typos, and distractor entities that share
  words with the target. Outputs a sorted JSON array of matching transactions.
---

# Bank Transaction Entity Filter

## Problem Shape

Given a CSV of bank transactions and a target company name (from the task instruction), extract every transaction belonging to that entity. The same company may appear under multiple name variants and account numbers. Some rows may only be identifiable through account-number evidence propagated from other rows. Separately named entities that share words with the target must be excluded.

## Algorithm: Connected-Components Evidence Propagation

This is not a simple string-filter problem. It is a bipartite-graph connected-components problem where rows are edges connecting company-name nodes to account-number nodes.

### Step 1 — Parse

Read the CSV preserving all values as exact strings. Note the column names — the output must use the exact CSV header keys.

### Step 2 — Seed Identification (Fuzzy Name Matching)

Extract the target entity name from the task instruction. Find all rows whose company name is a variant of the target.

**Normalization for comparison** (apply to both target name and candidate names):
- Lowercase
- Remove periods, commas, hyphens, apostrophes
- Collapse whitespace
- Strip only truly generic entity-type suffixes for content-word extraction: `group`, `holdings`, `hldgs`, `inc`, `llc`, `ltd`, `corp`, `co`, `company`
- **Do NOT strip** words like `capital`, `partners`, `north`, `west` — these are content words that distinguish the entity's identity

**Matching criteria** — a name is a target variant if, after normalization:
- Its content words substantially overlap with the target's content words
- Content words = all words after normalization, minus only generic entity-type suffixes
- Allow for: transposition ("Northwest" vs "North West"), minor spelling typos (Levenshtein distance ≤ 2 on individual words)
- Require: at least 2 content words matching (fuzzy) between candidate and target, OR ≥50% of target's content words matched

**Data-driven abbreviation discovery** (iterative refinement):
1. **First pass**: Find obvious matches using the normalization above
2. **Infer patterns**: From matched rows, identify abbreviation patterns. For example:
   - If "N.W. Capital Holdings" matches "North West Capital", then "N.W." is an abbreviation for "North West"
   - If "Cap. Group" matches "Capital Group", then "Cap." is an abbreviation for "Capital"
3. **Second pass**: Apply discovered abbreviation patterns to find additional matches
4. **Iterate**: Repeat until no new matches are found

This approach generalizes to any target company, not just v01's "North West Capital".

**Distractor exclusion** — CRITICAL. A name is NOT a target variant if:
- It contains a disambiguating business-type suffix that makes it a separately named entity
- Common distractor patterns: `advisors`, `advisory`, `partners`, `associates`, `consulting`, `management`, `ventures`, `advisers`
- **Data-driven distractor discovery**: If a name shares words with the target but has a different business-type suffix (e.g., "Advisors" vs "Group"), it's likely a separate entity
- The key test: would a human consider this the same legal entity or a different one? Shared words alone are insufficient.

### Step 3 — Evidence Collection

From seed rows, collect:
- `known_names`: set of all company-name strings found in seed rows
- `known_accounts`: set of all account-number strings found in seed rows
- `target_rows`: set of row indices

### Step 4 — Account-Number Exactness and Near-Miss Filtering

**CRITICAL**: Account numbers are exact identifiers. The task instruction explicitly states: "do not treat one-character-near account numbers as equal."

**Apply this filter BEFORE propagation:**
1. Count how many seed rows each account number appears on
2. For each pair of account numbers in `known_accounts` that differ by exactly one character:
   - If one account appears on multiple seed rows and the other appears on only one seed row, **exclude the single-occurrence account**
   - If both accounts appear on multiple seed rows, keep both (they're genuinely different accounts)
3. **Maintain an `excluded_accounts` set** containing all removed account numbers
4. Remove excluded accounts from `known_accounts`
5. **Remove any seed rows that have an excluded account from `target_rows`**
6. Also remove the excluded account's associated name from `known_names` if that name only appeared on excluded rows

**Example**: If BUS-41777 appears on 4 seed rows and BUS-41877 appears on 1 seed row, and they differ by one character, exclude BUS-41877 from `known_accounts`, add it to `excluded_accounts`, and remove the BUS-41877 row from `target_rows`.

**Why this rule**: The task instruction's explicit prohibition against treating one-character-near accounts as equal takes precedence over name-matching evidence. This filter must run BEFORE propagation to prevent excluded accounts from being used to propagate identity.

### Step 5 — Propagation Loop (Fixed-Point Iteration)

Repeat until no changes occur in an iteration:

For each row not yet in `target_rows`:
- **CRITICAL GUARD**: If the row's account number is in `excluded_accounts`, **skip this row entirely** — do not propagate through it
- **Account propagation**: If the row's account number is in `known_accounts`:
  - Add row to `target_rows`
  - Add row's company name to `known_names`
  - Add row's account number to `known_accounts` (may already be there)
- **Name propagation**: If the row's company name is in `known_names`:
  - Add row to `target_rows`
  - Add row's account number to `known_accounts` (but NOT if it's in `excluded_accounts`)
  - Add row's company name to `known_names` (may already be there)

This handles:
- Rows with short/ambiguous aliases that share an established account number
- Rows with established names but new account numbers (multi-account companies)
- Chain propagation: name→account→new-name→new-account→...

**Why the guard is essential**: Without checking `excluded_accounts` before propagation, name propagation can re-introduce excluded accounts. For example, if "N.W. Capital Holdings" is in `known_names` (because it appears on BUS-41777 rows), name propagation would find the BUS-41877 row and add it back to `target_rows`, undoing the Step 4 exclusion.

### Step 6 — Output

- Filter to `target_rows`
- Sort by `Date` ascending (lexicographic sort works for ISO dates)
- Write as a JSON array of objects
- Each object has exactly the CSV column keys as its keys
- All values are strings, preserved exactly from the CSV (do not parse amounts as numbers, do not reformat dates)
- No top-level wrapper object — just the array

## Key Principles

1. **Account numbers are exact identifiers, not numbers.** "BUS-41777" and "BUS-41877" are ALWAYS different accounts — even if they differ by one character and share the same company name. The task instruction explicitly says: "do not treat one-character-near account numbers as equal."
2. **Name similarity alone is insufficient for inclusion.** "North West Capital Advisors" shares words with the target but is a different entity.
3. **Propagation is essential.** Some rows may have no recognizable name variant but share an account number established by other rows.
4. **Distractors require positive exclusion, not just absence of match.** Actively check for separately-named entities that overlap with the target.
5. **Preserve everything exactly.** No numeric parsing, no date reformatting, no whitespace normalization in output values.

## Variation Handling (from spec)

| Dimension | How the skill adapts |
|-----------|---------------------|
| **company_identity_signal_variation** | The fuzzy matching in Step 2 must handle the full spectrum: clean names, punctuation variants, abbreviations, legal-suffix changes, spelling typos, partial names, and cases where one identifier is only trustworthy after reconciling against the other. |
| **transaction_membership_inference** | The propagation loop in Step 5 handles: multiple accounts per company, sparse anchor rows, indirect evidence chains, and datasets requiring full transitive closure. |
| **distractor_entity_confusability** | The distractor exclusion in Step 2 and the exact-match requirement for accounts in Step 4 handle: near-miss company names, similar account numbers (one character apart), subsidiaries/partners, and precision-critical filtering. |

## Reference Implementation Pattern (Python)

```python
import csv, json, re
from collections import defaultdict

def normalize_basic(name):
    """Basic normalization: lowercase, remove punctuation, collapse whitespace."""
    n = name.lower().strip()
    n = re.sub(r'[.\-,\'"]', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

GENERIC_SUFFIXES = {'group', 'holdings', 'hldgs', 'inc', 'llc', 'ltd',
                    'corp', 'co', 'company', 'corporation', 'limited',
                    'incorporated'}

def content_words(name):
    """Extract content words, stripping only generic entity-type suffixes."""
    words = normalize_basic(name).split()
    return [w for w in words if w not in GENERIC_SUFFIXES]

def words_fuzzy_match(w1, w2, max_dist=2):
    """Check if two words match allowing minor typos/abbreviations."""
    if w1 == w2:
        return True
    if w1.startswith(w2) or w2.startswith(w1):
        return True
    if abs(len(w1) - len(w2)) > max_dist:
        return False
    dist = sum(1 for a, b in zip(w1, w2) if a != b)
    dist += abs(len(w1) - len(w2))
    return dist <= max_dist

DISTRACTOR_PATTERNS = {'advisors', 'advisory', 'partners', 'associates',
                       'consulting', 'management', 'ventures', 'advisers'}

def is_distractor(name):
    """Check if name contains a disambiguating suffix indicating a separate entity."""
    norm = normalize_basic(name)
    for dw in DISTRACTOR_PATTERNS:
        if dw in norm.split():
            return True
    return False

def is_target_variant(name, target_name, abbr_map=None):
    """Check if name is a variant of target, excluding distractors."""
    if is_distractor(name):
        return False
    
    target_words = content_words(target_name)
    name_words = content_words(name)
    
    if not target_words:
        return False
    
    # Apply abbreviation expansion if available
    if abbr_map:
        expanded_words = []
        for w in name_words:
            expanded = abbr_map.get(w, w)
            expanded_words.extend(expanded.split() if isinstance(expanded, str) else [expanded])
        name_words = expanded_words
    
    matched = 0
    for tw in target_words:
        for nw in name_words:
            if words_fuzzy_match(tw, nw):
                matched += 1
                break
    return matched >= 2 or matched / len(target_words) >= 0.5

def discover_abbreviations(seed_names, target_name):
    """Infer abbreviation patterns from seed names that match the target."""
    abbr_map = {}
    target_words = content_words(target_name)
    
    for name in seed_names:
        name_words = content_words(name)
        # Look for short words in name that might abbreviate target words
        for nw in name_words:
            # Check ORIGINAL name for periods, not normalized (normalization removes them)
            if len(nw) <= 3 and '.' in name:
                # Potential abbreviation - check if it maps to a target word
                for tw in target_words:
                    if tw.startswith(nw) or nw in tw[:3]:
                        abbr_map[nw] = tw
    
    return abbr_map

def accounts_differ_by_one(acct1, acct2):
    """Check if two account numbers differ by exactly one character."""
    if len(acct1) != len(acct2):
        return abs(len(acct1) - len(acct2)) == 1
    return sum(1 for a, b in zip(acct1, acct2) if a != b) == 1

# Main algorithm:
# 1. Parse CSV
# 2. First pass: find obvious seed matches
# 3. Discover abbreviation patterns from seeds
# 4. Second pass: apply abbreviations to find more matches
# 5. Collect evidence (names, accounts, rows)
# 6. Near-miss account filtering (exclude single-occurrence near-misses)
# 7. Propagation loop with excluded_accounts guard
# 8. Output sorted JSON
```
