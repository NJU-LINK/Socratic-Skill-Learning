---
name: bank-trans-filter
description: General starting point for solving tasks in the bank-trans-filter family.
---

# bank-trans-filter

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Handling Distractor Accounts

- **Strict Account Matching**: Treat account numbers as the absolute unique identifier. Require mutual consistency between identifiers; do not propagate identity based on a single matching identifier if the other is suspicious.
- **One-Character-Near Distractors**: If an account number differs from a target account by only one or two characters (e.g., `BUS-41877` vs `BUS-41777`), treat it as a completely distinct entity and a high-risk distractor. Exclude single-occurrence rows on these accounts.
- **Name vs. Identifier Conflicts**: Exclude near-match accounts even if their company name exactly matches the target entity. Never propagate target membership or identity evidence based solely on a matching company name when the account number differs.