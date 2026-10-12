# Bank Transaction Filter - Skill Development Summary

## Problem Statement

Filter bank transactions to extract only those belonging to a target company, where the target appears under multiple name variants with abbreviations, legal-suffix changes, and potential typos. Must exclude separate entities with similar names.

## Key Insights Discovered

### 1. Legal Suffixes vs. Functional Descriptors (Core Principle)

**Legal-entity suffixes** (Group, Holdings, Corp, Inc, Ltd, LLC, Co) describe a company's legal form and are used interchangeably for the same entity.

**Functional business descriptors** (Advisors, Advisory, Partners, Consulting, Services) describe a line of business and typically indicate a distinct legal entity.

This distinction drives the include/exclude decision:
- "North West Capital Group" + "North West Capital Holdings" → same entity (legal suffix variation)
- "North West Capital" + "North West Capital Advisors" → separate entities (functional descriptor)

### 2. Algorithmic Discovery (Not Hardcoded Answers)

The skill must discover which names are aliases, not have them pre-specified. The algorithm:

1. **Extract target core terms** from the target name (e.g., "North West Capital" → {"north", "west", "capital"})
2. **Data-driven abbreviation expansion**: Scan dataset for patterns like "N.W." or "Cap." and expand using dataset vocabulary
3. **Require complete overlap**: Candidate name must contain ALL target core terms (not partial match)
4. **Classify modifiers**: Legal suffixes → include; functional descriptors → exclude
5. **Account propagation**: Use shared account numbers to catch short/unrecognizable aliases

### 3. Critical Bug Fix: Partial Overlap Trap

**Bug**: Using `words.issubset(target_core)` would incorrectly include "Capital Group" (shares one word with "North West Capital").

**Fix**: Only use `target_core.issubset(words)` — candidate must contain ALL target core terms.

This prevents false positives where a single shared word triggers inclusion.

### 4. Compound Word Handling

"Northwest" (one word) should match "North West" (two words) when the target uses the split form. The algorithm detects compound words in the target and splits them in candidates.

### 5. Account Number Propagation

After name-based classification, collect all confirmed target accounts. Then include any rows on those accounts, even if the company name is short or unrecognizable. This catches aliases that are too abbreviated to match by name alone.

## v01 Verification

The algorithm correctly handles v01:

**Included (target aliases)**:
- North West Capital Group
- North West Cap. Group (abbreviation: Cap. → Capital)
- N.W. Capital Holdings (abbreviation: N.W. → North West)
- N.W. Capital Hldgs (abbreviation: Hldgs → Holdings)

**Excluded (separate entities)**:
- North West Capital Advisors (functional descriptor: Advisors)
- North West Capital Advisory (functional descriptor: Advisory)
- Northwest Capital Advisors (functional descriptor: Advisors)
- Northwest Capital Partners (functional descriptor: Partners)

**Result**: 14 matching transactions, correctly filtered and sorted by date.

## Generalization to Unseen Variants

The skill is now truly algorithmic:

1. **Target name extraction**: Works for any target company name from task instructions
2. **Data-driven abbreviations**: Derives expansion rules from dataset vocabulary, not hardcoded dictionaries
3. **Complete overlap requirement**: Prevents false positives on any dataset
4. **Legal vs. functional classification**: General principle applicable to any corporate naming convention
5. **Account propagation**: Catches edge cases where names are too short or corrupted

## Verification Checklist for Future Applications

- [ ] Target name extracted from task instructions (not hardcoded)
- [ ] Abbreviation expansion is data-driven from dataset vocabulary
- [ ] Name matching requires ALL target core terms (not partial overlap)
- [ ] Legal suffixes treated as interchangeable; functional descriptors as separate entities
- [ ] Account propagation catches short/unrecognizable aliases on confirmed accounts
- [ ] Account numbers preserved exactly as strings (no numeric parsing)
- [ ] One-character-near accounts handled cautiously (only with strong name evidence)
- [ ] Output sorted by date ascending
- [ ] Output is JSON array with correct keys, no wrapper object
- [ ] All values are strings preserved exactly from CSV
