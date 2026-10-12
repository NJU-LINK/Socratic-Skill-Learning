---
name: financial-document-processor
description: General starting point for solving tasks in the financial-document-processor family.
---

# financial-document-processor

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Document Classification & Workflow
1. **Prioritize Classification**: Determine the document type using high-level cues (document title, headers, payment status) *before* investing time in detailed OCR or field extraction.
2. **Invoices vs. Receipts**: 
   - **Invoices** request payment. Require strong markers such as an explicit "Invoice" label, "Amount Due", "Payable Total", "Billing Statement", "Bill To" fields, or invoice/reference numbers.
   - **Receipts** confirm payment already made. Look for markers like "Receipt", "Card Payment Approved", "Total Paid", "Transaction Approved", or "Paid in Full". 
   - **Routing**: Do not classify point-of-sale receipts as invoices, even if they contain well-formed financial fields like subtotal, VAT, or total amounts. Route receipts to the appropriate non-invoice category (e.g., `other` or `receipts` as specified by the task).

## Processing Pipeline & OCR
- **Dynamic Pipeline**: Build a generalized, dynamic Python script that iterates over the input directory, applies text extraction/OCR, evaluates classification heuristics, parses amounts, and generates the summary CSV programmatically. **Do not hardcode** extracted data, classifications, or amounts.
- **OCR Validation**: Never hardcode guessed financial values when OCR output is inconsistent or garbled. Use mathematical consistency checks (e.g., subtotal + tax = total) or consensus voting to validate extracted fields.
- **Graceful Degradation**: If preprocessing fails to stabilize OCR output, flag the extraction as uncertain or leave fields empty rather than guessing.
