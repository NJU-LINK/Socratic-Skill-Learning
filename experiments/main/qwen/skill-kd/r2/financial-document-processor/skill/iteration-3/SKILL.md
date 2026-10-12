---
name: financial-document-processor
description: Reusable instructions for financial-document-processor tasks.
---

# financial-document-processor

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Invoice classification by payment direction
content: When classifying documents as invoice versus other, determine the document's payment direction from body-language cues: classify as invoice when the document requests payment from the recipient (e.g., amount due, payable total, please remit), and classify as other when it instead confirms a completed payment, reports internal expenses, proposes a pending purchase, or reminds about an existing obligation, regardless of whether the document contains monetary totals or tax figures.
