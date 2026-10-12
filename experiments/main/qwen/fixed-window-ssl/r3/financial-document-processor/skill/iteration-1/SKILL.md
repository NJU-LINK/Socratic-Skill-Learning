---
name: financial-document-processor
description: Process mixed batches of financial documents (PDFs and images) by classifying them as invoices or other document types, extracting financial amounts from invoices, and organizing files into appropriate directories with a summary report.
---

# Financial Document Processor

## Overview

This skill processes mixed batches of financial documents (PDFs and images like JPG/PNG) to:
1. Classify each document as an invoice or non-invoice
2. Extract `total_amount` and `vat_amount` from invoices
3. Move invoices to `/app/invoices/` and non-invoices to `/app/other/`
4. Generate `/app/invoices/summary.csv` with extracted amounts and totals

## Core Methodology

### 1. Document Classification (Scoring-Based Approach)

**Principle**: Use a weighted scoring system rather than veto-based classification. Accumulate evidence from multiple signals instead of relying on single keywords.

**Positive signals** (each adds to score):
- Financial amount indicators: "amount due", "grand total", "total due", "payable total", "total paid"
- Tax indicators: "vat", "sales tax", "tax" (followed by amounts)
- Recipient indicators: "bill to", "customer", "ship to"
- Document type indicators: "invoice", "billing statement", "charge note", "tax document", "receipt"
- Payment indicators: "please remit", "subtotal"

**Negative signals** (each subtracts weighted amount):
- Explicit negations: "not a tax invoice", "not an invoice" (weight: 5)
- Pre-invoice documents: "purchase order" (weight: 4), "pending" (weight: 2), "estimated tax" (weight: 2)
- Internal documents: "expense reimbursement" (weight: 4), "reimbursement summary" (weight: 3)
- Reminders/notifications: "payment reminder" (weight: 3), "outstanding balance" (weight: 2)

**Classification rule**: Classify as invoice when score ≥ threshold (configurable, typically 3).

**Why this works**: Documents like "Remittance Notice" with subtotal + tax + total + customer address score positively despite neutral title. Documents like "Payment Reminder" with "not a tax invoice" score negatively despite containing financial amounts.

### 2. Text Extraction

**For PDFs**: Use PyMuPDF (`fitz`) to extract embedded text from all pages.

**For images**: Run OCR with multiple Page Segmentation Modes (PSM) to capture different content:
- PSM 3: Fully automatic
- PSM 6: Assume a single uniform block of text
- PSM 11: Sparse text

Collect all extraction results separately. Do not pick one "best" text — use all runs for frequency voting.

### 3. Amount Extraction (Multi-PSM Frequency Voting + Arithmetic Consistency)

**Principle**: When OCR produces conflicting numeric values, prefer the most frequently observed value across extraction passes. Use arithmetic consistency only to validate decimal scale, not to select among competing values.

**Algorithm**:

1. **Collect per-run tuples**: For each PSM run, extract (subtotal, tax, total) independently.

2. **Handle percentage patterns**: When a line reads "VAT 10%: 128.00", extract 128.00 as the tax amount, not 10. Skip numbers followed by "%" when extracting tax amounts.

3. **Find optimal decimal scale**: Try all combinations of decimal scales (1, 10, 100, 1000, 0.1, 0.01) for each field. Score each combination by arithmetic consistency:
   - If all three fields present: check if subtotal + tax ≈ total (within 2% tolerance)
   - If only subtotal and tax: check if tax rate is reasonable (5-25% of calculated total)
   - Pick the scale combination with highest consistency score

4. **Apply best scales and extract final values**: Use the most frequent value at the optimal scale for each field.

5. **Calculate total**: If subtotal and tax are available, calculate total = subtotal + tax. Use OCR-captured total only for scale validation.

**Why this works**: OCR may drop decimal points (e.g., "483" instead of "4.83"). By trying multiple scales and checking arithmetic consistency, the algorithm finds the scale that makes subtotal + tax ≈ total across the most PSM runs.

### 4. CSV Output

Write `summary.csv` with columns: `filename`, `total_amount`, `vat_amount`.

- One row per invoice
- Final row with `filename="total"` and summed amounts
- **Format all amounts to exactly 2 decimal places** (e.g., "54.10" not "54.1")

## Implementation

See `scripts/process_documents.py` for the complete implementation.

**Key dependencies**:
- `fitz` (PyMuPDF) for PDF text extraction
- `pytesseract` and `PIL` for image OCR
- Standard library: `os`, `re`, `csv`, `shutil`, `collections.Counter`

**Usage**:
```bash
python3 scripts/process_documents.py
```

The script expects:
- Input documents in `/app/documents/`
- Creates `/app/invoices/` and `/app/other/` directories
- Generates `/app/invoices/summary.csv`

## Generalization Notes

This methodology handles:
- **OCR noise**: Multi-PSM extraction + frequency voting + arithmetic validation
- **Varied document types**: Scoring-based classification with weighted signals
- **Different amount formats**: Handles "VAT 10%: 128.00", "Tax: 55.68", "VAT included 4.83", etc.
- **Missing fields**: Calculates total from subtotal + tax when total is not explicitly captured
- **Decimal scale errors**: Automatically corrects OCR errors like "483" → "4.83"

**Configurable parameters**:
- Classification threshold (default: 3)
- Arithmetic tolerance (default: 2%)
- Tax rate range (default: 5-25%)
- PSM modes to try (default: 3, 6, 11)
