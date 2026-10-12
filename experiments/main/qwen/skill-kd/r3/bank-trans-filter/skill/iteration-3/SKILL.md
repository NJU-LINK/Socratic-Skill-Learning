---
name: bank-trans-filter
description: Reusable instructions for bank-trans-filter tasks.
---

# bank-trans-filter

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Near-match identifier distractor exclusion
content: When propagating entity membership across rows using fuzzy name matching, exclude any row whose account or identifier differs by only one or two characters from an already-established target account, even when the row's name matches a known target alias, because such near-match identifiers signal distractors or data corruption rather than genuine target evidence.
