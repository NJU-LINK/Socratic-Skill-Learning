---
name: bank-trans-filter
description: General starting point for solving tasks in the bank-trans-filter family.
---

# bank-trans-filter

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Entity Resolution and Filtering
- **Strict Account Identifiers**: Treat account numbers as strict, immutable identifiers. Always use exact string matching for account numbers.
- **Near-Miss Distractor Filtering**: When building the set of target accounts, compute pairwise string distances to identify near-miss accounts. Strictly exclude transactions from accounts that differ by only one or two characters from an established target account (e.g., `BUS-41877` vs `BUS-41777`).
- **Name Matching Does Not Override**: Do not include near-miss distractor accounts even if the company name or other attributes exactly match a known target or alias. Name-based alias matching must never override the strict distinctness of account numbers.
