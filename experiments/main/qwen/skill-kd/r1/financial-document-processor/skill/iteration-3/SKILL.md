---
name: financial-document-processor
description: Reusable instructions for financial-document-processor tasks.
---

# financial-document-processor

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Invoice versus non-invoice classification
content: When classifying financial documents, determine invoice status from document content rather than the document title: label a document as invoice when its content bills or requests payment from a customer (amounts described as payable, due, or to be remitted); classify receipts confirming completed payments, purchase orders, payment reminders, and internal expense summaries as non-invoices even when they contain tax amounts and totals.
