---
name: financial-document-processor
description: General starting point for solving tasks in the financial-document-processor family.
---

# financial-document-processor

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Workflow

### 1. Multi-modal Text Extraction & OCR
- **Text-based PDFs**: Use `pdftotext` or `fitz` (PyMuPDF).
- **Images/Scanned PDFs**: Use `pytesseract` with PIL preprocessing (convert to grayscale, increase contrast, 2x upscale). For noisy scans, run multi-pass OCR using different PSM modes (e.g., 3, 4, 6).
- **Arithmetic Cross-Validation**: Resolve ambiguous digit readings by ensuring `total_amount = subtotal + vat_amount` and `vat_amount ≈ subtotal × common_rate` (e.g., 8-10%). Select the reading that satisfies these constraints.

### 2. Semantic Classification with Negation Handling
- Rely on semantic content cues, not filenames or title labels.
- **Invoice indicators**: Request-for-payment markers ('Amount Due', 'Total Due', 'Payable Total', 'Please remit', 'Billing Statement', 'Charge Note'), line-item descriptions, and tax/VAT breakdowns. Extract totals only from these.
- **Non-invoice indicators**: Proof of past payment ('Receipt', 'Total Paid', 'Card Payment Approved'), internal tracking ('Expense Reimbursement'), pre-approval ('Purchase Order', 'Approval Status: Pending').
- **Crucial**: Check for explicit negations or disclaimers (e.g., "This notice is not a tax invoice") to avoid false positives.

### 3. CSV Summary Generation & Validation
- Generate `summary.csv` with exact required columns (e.g., `filename`, `total_amount`, `vat_amount`), one row per classified invoice sorted by filename.
- Use Python's `csv.writer`, formatting amounts to 2 decimal places.
- Programmatically compute the final `total` sum row in memory and append it to the CSV.
- Validate that the sum of individual rows matches the `total` row before finishing.