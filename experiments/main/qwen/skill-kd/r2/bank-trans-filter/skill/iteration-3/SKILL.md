---
name: bank-trans-filter
description: Reusable instructions for bank-trans-filter tasks.
---

# bank-trans-filter

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Near-miss account rejection during entity resolution
content: When building the set of identifiers belonging to a target entity, accept identifiers in order of supporting evidence and exclude any candidate identifier that differs by only one or two characters from an already-accepted identifier, rejecting all rows on the near-miss identifier even when its name matches a target alias.
