# Bank Transaction Filter - Implementation Notes

## Key Design Decisions

### 1. Two-Phase Evidence Propagation

The core algorithm uses two interleaved phases:

**Phase A (Name-Based Anchoring with Corroboration):**
- Normalize company names by expanding abbreviations and removing punctuation
- Strip generic legal suffixes (Group, Holdings, Inc, LLC, etc.) to get core identity tokens
- Identify rows whose core tokens overlap ≥80% with target core tokens (exact) or have ≥55% character similarity (fuzzy)
- Exclude rows with distinguishing suffixes (Advisors, Partners, Advisory, etc.)
- **Corroboration requirement**: Group name-matching rows by account number
  - Accounts with ≥2 matching rows → established (corroborated evidence)
  - Accounts with 1 matching row → only established if exact token match AND lightweight suffix (Group, Inc, LLC, Corp)
  - Heavy suffixes like "Holdings" require multi-row corroboration to prevent false positives from near-miss accounts

**Phase B (Account-Based Propagation):**
- Collect account numbers from anchor rows
- Find all rows sharing those accounts
- Include rows even with shorter/ambiguous names if they don't have distinguishing suffixes
- Iterate until convergence

### 2. Legal Suffix Discrimination

**Generic suffixes (stripped, indicate same entity):**
- Group, Holdings, Inc, LLC, Corp, Corporation, Ltd, Limited, Co, Company, PLC, GmbH, AG, SA, NV

**Lightweight suffixes (safe for single-row account establishment):**
- Group, Inc, LLC, Corp, Corporation, Ltd, Limited, Co, Company
- These are truly generic structural markers that don't add semantic weight

**Heavy suffixes (require multi-row corroboration):**
- Holdings, PLC, GmbH, AG, SA, NV
- These indicate more complex organizational structures and require corroborating evidence

**Distinguishing suffixes (kept, indicate separate entities):**
- Advisors, Advisory, Partners, Consulting, Management, Associates, Solutions, Services, Ventures, Fund, Trust

**Rationale:** Generic structural suffixes don't change the fundamental business identity. "North West Capital Group" and "North West Capital Holdings" are the same company with different legal structures. However, "North West Capital Advisors" is a different business entity providing advisory services. For account establishment, lightweight suffixes are safe for single-row matches, but heavy suffixes like "Holdings" require multiple corroborating rows to prevent false positives from near-miss account numbers.

### 3. Abbreviation Handling

Common abbreviations are expanded before comparison:
- N.W. → North West
- Cap. → Capital
- Hldgs → Holdings
- Intl → International
- Mfg → Manufacturing
- Ind → Industries
- Tech → Technology

**Critical:** Abbreviation expansion must happen BEFORE punctuation removal, otherwise patterns like "n.w." won't match correctly.

### 4. Exact Account Matching

Account numbers are identifiers, not numbers. The solution uses exact string equality only:
- "BUS-30001" ≠ "BUS-30071" (one character difference)
- "BUS-41777" ≠ "BUS-41877" (one character difference)
- No fuzzy matching, no numeric comparison

### 5. Two-Layer Name Matching Strategy

The name matching uses two layers to balance precision and recall:

**Layer 1: Exact Token-Set Intersection (Primary)**
- Fast and precise for clean data
- Requires exact token matches after normalization
- Example: "North West Capital Group" matches target "North West Capital" because core tokens {north, west, capital} match exactly

**Layer 2: Character-Bigram Similarity (Fallback)**
- Handles typos and spelling drift using Dice coefficient on character bigrams
- For each target token, finds the best-matching variant token
- Coverage = fraction of target tokens with at least one variant token above 55% similarity
- Example: "Nrth West Capital" with tokens {nrth, west, capital}:
  - "nrth" vs "north" → 57% similarity ✓
  - "west" vs "west" → 100% similarity ✓
  - "capital" vs "capital" → 100% similarity ✓
  - Coverage: 3/3 = 100% (above 80% threshold, accepted)
- Example: "Nrth Wst Cpital" with tokens {nrth, wst, cpital}:
  - "nrth" vs "north" → 57% similarity ✓
  - "wst" vs "west" → 40% similarity ✗ (too short, below 55% threshold)
  - "cpital" vs "capital" → 73% similarity ✓
  - Coverage: 2/3 = 67% (below 80% threshold, rejected)
- This prevents false positives while catching genuine typos

**Threshold rationale:**
- Token threshold: 55% - catches common typos like "nrth" → "north" (57%) while rejecting very short tokens like "wst" → "west" (40%)
- Coverage threshold: 80% - requires most target tokens to match, preventing false positives from partial matches

**Why not purely fuzzy?**
- Character-level matching alone can match unrelated companies
- Two-layer approach: exact matching for precision, fuzzy fallback for recall
- Distinguishing suffixes (Advisors, Partners) are never stripped, even with fuzzy matching

### 5. Evidence Propagation vs. Simple Filtering

The solution doesn't just filter by name matching. It propagates evidence through accounts:
1. A clear name match establishes an account as belonging to the target
2. Other rows on that account are included even if their name is shorter or more ambiguous
3. This handles cases where the same company uses different name variants on different transactions

### 6. Account Corroboration Mechanism

The corroboration requirement prevents false positives from single-row accounts with near-miss account numbers:

**Two-stage anchor discovery:**
1. **Stage 1**: Find all name-matching rows and group by account number
2. **Stage 2**: Establish accounts with corroboration:
   - ≥2 matching rows → established (corroborated evidence)
   - 1 matching row → only if exact token match AND lightweight suffix
   - Heavy suffixes (Holdings, PLC, etc.) require multi-row corroboration

**Why this matters:**
- BUS-41777 has 5 rows with "N.W. Capital Holdings" → established via corroboration
- BUS-41877 has 1 row with "N.W. Capital Holdings" → rejected (heavy suffix, no corroboration)
- BUS-41877 differs from BUS-41777 by one character (near-miss account)
- Without corroboration, BUS-41877 would be incorrectly included

**Lightweight vs heavy suffix distinction:**
- Lightweight (Group, Inc, LLC): Safe for single-row establishment because they're truly generic
- Heavy (Holdings, PLC): Require corroboration because they indicate more complex structures and are more likely to appear on near-miss accounts by coincidence

## v01-Specific Observations

### Target Company: North West Capital

**Included variants:**
- "North West Cap. Group" on BUS-30001 (abbreviation + suffix, 6 rows → established)
- "North West Capital Group" on BUS-30001 (full name + suffix, 2 rows → established)
- "N.W. Capital Holdings" on BUS-41777 (abbreviation + suffix, 3 rows → established via corroboration)
- "N.W. Capital Hldgs" on BUS-41777 (abbreviation + abbreviated suffix, 2 rows → established via corroboration)

**Excluded accounts:**
- BUS-41877: Single row with "N.W. Capital Holdings" (heavy suffix, no corroboration) → rejected

**Excluded distractors:**
- "Northwest Capital Advisors" on BUS-41707 (distinguishing suffix "Advisors")
- "North West Capital Advisors" on BUS-35001 (distinguishing suffix "Advisors")
- "North West Capital Advisory" on BUS-30071 (distinguishing suffix "Advisory", account one char off from 30001)
- "Northwest Capital Partners" on BUS-41770 (distinguishing suffix "Partners")
- "Northern Light Energy" on BUS-27749, BUS-z7749 (completely different company)

### Key Precision Tests

1. **BUS-30071 vs BUS-30001**: One character difference in account number. Must be treated as different accounts.
2. **"Advisory" suffix**: Even though the name is very similar, "Advisory" indicates a separate entity.
3. **"Northwest" vs "North West"**: Word boundary variation combined with distinguishing suffix indicates separate entity.

## Generalization to Unseen Variants

The skill is parameterized on the target company name and handles:

1. **Severe spelling drift**: Typos in company names (e.g., "Mounta5n" vs "Mountain")
2. **Multiple abbreviation patterns**: N.W., NW, Cap., Hldgs, etc.
3. **Legal suffix variations**: Group, Holdings, Inc, LLC, etc.
4. **Multiple accounts per company**: A company may have several account numbers
5. **Near-miss distractors**: Names/accounts that are similar but not identical
6. **Evidence propagation**: Identity evidence flows through accounts, not just name matching

## Testing Checklist

- [ ] All name variants of target are identified
- [ ] All rows on target accounts are included
- [ ] Distractors with distinguishing suffixes are excluded
- [ ] Near-miss accounts are not conflated
- [ ] Output is valid JSON array
- [ ] Output is sorted by Date ascending
- [ ] All values are preserved as strings from CSV
- [ ] No wrapper object in JSON output
