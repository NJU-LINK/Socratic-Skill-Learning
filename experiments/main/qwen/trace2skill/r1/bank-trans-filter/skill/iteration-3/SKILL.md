---
name: bank-trans-filter
description: General starting point for solving tasks in the bank-trans-filter family.
---

# bank-trans-filter

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Account Matching & Distractor Handling

When identifying and filtering transactions for target entities:
1. **Exact Account Match Only**: Always use exact string matching for account numbers. Propagate target status *only* to rows with an exact match. Never treat near-matches (e.g., one-character typos like `BUS-41877` vs `BUS-41777`) as the same account.
2. **Reject Near-Match Distractors**: Account numbers that differ by only one character are intentional synthetic distractors. **Do not** include them, even if the company name perfectly matches the target entity. Name identity never overrides strict account boundaries.
3. **Alias Directionality**: An established account (verified via exact ID match) can include rows with shorter or ambiguous company aliases. However, do not use a company name match to establish a *new* target account if its account number is a near-match to an already established target account; treat such rows as distractors.