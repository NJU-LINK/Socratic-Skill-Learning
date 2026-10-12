---
name: bank-trans-filter
description: Filter bank transactions to a target company using entity resolution with name variation handling, account propagation, and distractor exclusion
---

# Bank Transaction Filter

Filter bank transactions to extract only those belonging to a target company, handling name variations, abbreviations, typos, and multiple accounts while excluding similar-but-distinct entities.

## Task

Given a CSV file of bank transactions and a target company name, identify and extract all transactions belonging to that company. The output must be a JSON array sorted by date with exact string preservation.

## Usage

```bash
python scripts/solve.py <input_csv> <output_json> "<target_company_name>"
```

**Example:**
```bash
python scripts/solve.py /app/data/bank_transactions.csv /app/data/output.json "North West Capital"
```

## Algorithm

The solution uses a multi-phase entity-resolution approach:

### Phase 1: Seed Discovery
Find all rows whose company name matches the target under variation. This involves:
- **Normalization**: lowercase, expand abbreviations, strip punctuation, strip legal suffixes
- **Token-level fuzzy matching**: compare normalized tokens with bidirectional similarity checking

### Phase 2: Account Collection
Collect all account numbers from seed rows. These accounts are candidates for belonging to the target entity.

### Phase 3: Near-Account Resolution
When two seed accounts differ by only 1 character in their account number, the one with fewer matching rows is treated as a corruption/distractor and excluded. This implements the spec requirement: "do not treat one-character-near account numbers as equal." The algorithm:
1. Count evidence per account (number of rows with matching names)
2. Sort seed accounts by evidence count descending
3. Greedily add accounts to the established set; skip any that are within Levenshtein distance ≤ 1 of an already-established account

This handles cases where account numbers have typos (e.g., BUS-41777 vs BUS-41877) — the account with stronger evidence wins.

### Phase 4: Propagation
Include ALL rows on established accounts, even if their company name is shorter, corrupted, or uses a different alias. Once an account is linked to the target by a matching-name row, all rows on that account belong to the target.

### Phase 5: Output
Sort matched rows by Date ascending and output as JSON array with exact string values preserved.

## Key Design Decisions

### Legal Suffixes vs Functional Descriptors

**Legal suffixes** (Group, Holdings, LLC, Inc, Ltd, Corp, Co, Company) indicate corporate form, NOT entity identity. These are stripped during normalization because "ABC Corp" and "ABC LLC" are the same entity.

**Functional descriptors** (Advisors, Advisory, Partners, Associates, Consulting) indicate DIFFERENT entities. These are NOT stripped. "ABC Advisors" is a separate entity from "ABC" and must be excluded.

The bidirectional token similarity check naturally handles this: if the candidate has extra tokens not in the target (like "advisors"), the candidate_coverage drops below the threshold and the row is excluded.

### Abbreviation Handling

The script handles common abbreviation patterns:
- **Single-letter abbreviations**: "N.W." → "n w" (generic expansion)
- **Corporate abbreviations**: "Cap." → "capital", "Hldgs" → "holdings", "Corp" → "corporation"
- **Single-letter token matching**: A single letter token (e.g., "n") matches any target token starting with that letter (e.g., "north")

This allows "N.W. Capital Holdings" to match "North West Capital" after normalization.

### Bidirectional Token Similarity

The matching algorithm checks similarity in BOTH directions:
1. **Target coverage**: What fraction of target tokens are found in the candidate?
2. **Candidate coverage**: What fraction of candidate tokens are found in the target?

Both must exceed the threshold (default 0.85). This prevents:
- **False positives**: "North West Capital Advisors" has all target tokens but also has "advisors" → candidate_coverage = 3/4 = 0.75 < 0.85 → excluded
- **False negatives**: "N.W. Capital" has abbreviated tokens but they match target tokens via single-letter prefix matching → both coverages high → included

### Account Identity Rule

Account numbers are identifiers, not numbers. The script:
- **Never merges accounts** based on string similarity alone
- **Includes an account** only if at least one row on that account has a name match
- **Preserves account numbers exactly** in the output
- **Excludes near-accounts**: If two accounts are near-matches (1 character difference), they are NOT treated as separate legitimate entities — the one with less evidence is excluded as a likely typo/corruption

This implements the spec requirement that "non-target accounts that differ by only one or two characters from target accounts" are distractors to be excluded.

### Propagation Rule

Once an account is established by a matching-name row, ALL rows on that account are included, even if:
- The company name is shorter or corrupted
- The company name uses a different alias
- The account number has a typo in some rows

This handles cases where the same entity appears under multiple name variants across different transactions.

## Output Format

The output is a JSON array with these constraints:
- **No top-level wrapper**: just a JSON array
- **One object per matching row** with exactly these keys: `Company Name`, `Account Number`, `Date`, `Amount`, `Transaction Type`, `Description`
- **Sorted by Date ascending**
- **All values are strings** preserved exactly from the CSV (no numeric conversion, no date parsing)

## Limitations and Edge Cases

### Current Limitations

1. **Abbreviation expansion is generic**: The script expands common patterns (X.Y.Z., Cap., Hldgs) but doesn't know target-specific abbreviations. If the target is "Silverstone Financial" and it appears as "SF Inc", the script won't know "SF" means "Silverstone Financial".

2. **Overly broad abbreviation expansion**: The `\bcap\.?\b` → "capital" expansion can incorrectly match substrings. For example, "Fin." (meaning "Financial") doesn't match this pattern, but if a company appeared as "Silverstone Cap." it would expand to "Silverstone capital" which may or may not match "Silverstone Financial" depending on other tokens. The expansion works well for standalone "Cap." but can create mismatches in edge cases.

3. **Token similarity threshold**: The default 0.85 threshold works for most cases but may need tuning for very short or very long company names.

4. **No cross-row name inference**: The script doesn't infer that two different account numbers belong to the same entity based on name similarity. Each account must be independently established by a name match.

### When to Adjust

- **If getting too many false positives**: Increase `min_similarity` threshold (e.g., 0.9 or 1.0 for exact match)
- **If missing valid variants**: Decrease `min_similarity` threshold (e.g., 0.7 or 0.8)
- **If single-letter abbreviations aren't matching**: Check that the generic expansion `\b([a-z])\.` is working correctly
- **If legal suffixes aren't being stripped**: Add them to the `LEGAL_SUFFIXES` list

## Testing

To verify the script works correctly:

```bash
# Run the script
python scripts/solve.py input.csv output.json "Target Company"

# Check output
python -c "
import json
with open('output.json') as f:
    data = json.load(f)
print(f'Total rows: {len(data)}')
print(f'Dates sorted: {all(data[i][\"Date\"] <= data[i+1][\"Date\"] for i in range(len(data)-1))}')
print(f'All string values: {all(isinstance(v, str) for row in data for v in row.values())}')
print(f'Unique accounts: {sorted(set(r[\"Account Number\"] for r in data))}')
"
```

## Implementation Notes

The script is implemented in Python 3 and uses only standard library modules (csv, json, re, sys). No external dependencies are required.

The normalization and matching logic is designed to be extensible. Additional abbreviation patterns can be added to `normalize_name()`, and additional legal suffixes can be added to `LEGAL_SUFFIXES`.
