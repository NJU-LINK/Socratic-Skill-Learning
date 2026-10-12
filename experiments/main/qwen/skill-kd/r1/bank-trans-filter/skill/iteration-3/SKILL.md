---
name: bank-trans-filter
description: Reusable instructions for bank-trans-filter tasks.
---

# bank-trans-filter

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] One-character-near identifier exclusion
content: When a row's account number differs by exactly one character from an already-established target account, do not include that row even if its company name matches a known target alias, because near-miss identifiers indicate data corruption rather than a legitimate second account.
