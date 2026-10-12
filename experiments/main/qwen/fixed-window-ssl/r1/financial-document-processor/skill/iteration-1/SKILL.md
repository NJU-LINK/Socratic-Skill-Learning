---
name: financial-document-processor
description: >
  Classify mixed batches of financial/business documents as invoice or other,
  route them to appropriate output folders, extract total_amount and vat_amount
  from invoices, and produce a summary CSV with per-invoice rows plus a totals row.
  Robust to OCR noise, varied document titles, and diverse financial field expressions
  by using mathematical structure detection (golden triplets) rather than keyword matching.
---

# Financial Document Processor

## Overview

Process a batch of mixed financial/business documents (PDFs and images) by:
1. Classifying each document as `invoice` or `other`
2. Moving invoices to `/app/invoices/` and non-invoices to `/app/other/`
3. Extracting `total_amount` and `vat_amount` from each invoice
4. Writing `/app/invoices/summary.csv` with per-invoice rows plus a totals row

## Core Architecture: Golden Triplet Detection

The fundamental insight is that **invoices have a mathematical invariant**: `subtotal + tax = total`. This structural property is far more robust than keyword matching because:
- Numbers survive OCR better than words
- The mathematical relationship holds regardless of document title or layout
- It works across languages, currencies, and formatting conventions

### Algorithm

```
1. Extract text from document (PDF: pdftotext; Images: tesseract with multiple PSM modes)
2. Normalize text: strip commas, lowercase
3. Extract ALL monetary amounts using pattern: (\d+(?:\.\d{1,2})?)
4. Find "golden triplets": (a, b, c) where a + b ≈ c (within tolerance 0.02)
5. Check for explicit disclaimers that disqualify as invoice
6. Classification:
   - If disclaimer present → OTHER (overrides everything)
   - If golden triplet exists → INVOICE
   - Fallback: strong invoice keywords + total field → INVOICE
   - Otherwise → OTHER
7. For invoices, extract financial data:
   - vat_amount = min(a, b) from best triplet
   - total_amount = c (the sum)
   - Cross-validate with mathematical consistency
```

## Implementation Details

### Text Extraction

**PDFs**: Use `pdftotext` command-line tool.

**Images**: Use `tesseract` with multiple PSM (Page Segmentation Mode) values to maximize OCR coverage:
- PSM 6: Assume a single uniform block of text
- PSM 3: Fully automatic
- PSM 4: Assume a single column of text of variable sizes
- PSM 11: Sparse text, no particular order
- PSM 12: Sparse text with OSD

Combine outputs from all passes to capture text that any single mode might miss.

### Text Normalization

Before amount extraction and pattern matching:
1. Strip all commas: `text.replace(',', '')`
2. Lowercase: `text.lower()`

This ensures "1,280.00" becomes "1280.00" and matches consistently.

### Amount Extraction

Use simple pattern: `(\d+(?:\.\d{1,2})?)`

This matches:
- Integers: 980, 1280, 2450
- Decimals: 55.68, 751.68, 1058.40

Filter out amounts ≤ 0.005 to remove noise.

### Golden Triplet Detection

For all unique amounts, find triplets (a, b, c) where:
- a + b ≈ c (within tolerance 0.02)
- a < b (so a is typically tax, b is subtotal)

Return all such triplets as candidates.

### Disclaimer Detection

Explicit disclaimers override even the presence of a golden triplet. Check for OCR-tolerant patterns:

**Payment confirmations (receipts)**:
- `card\s+\w+\s+(approved|aproved|aeproved)` — handles "card fayment aeproved"
- `total\s+(paid|pe?t)` — handles "total pet"
- `recei[cpb]t` — handles "receict", "receibt"

**Non-invoice documents**:
- `not\s+(a\s+)?tax\s+invoice` — explicit disclaimer
- `this\s+notice\s+is\s+not` — partial disclaimer
- `expense\s+reimbursement` — internal document
- `reclaimable\s+tax` — reimbursement signal
- `approval\s+status\s*:\s*pending` — purchase order
- `approved\s+spend\s+ceiling` — purchase order
- `purchase\s+order` — PO document

### Classification Logic

```python
if has_disclaimer(text):
    return False  # Not an invoice

if golden_triplets_exist:
    return True  # Invoice

# Fallback: strong keywords + total field
if matches_invoice_keywords(text) and has_total_field(text):
    return True

return False
```

### Financial Data Extraction

For invoices with golden triplets:
1. Select best triplet using label-based scoring (see below)
2. `vat_amount = min(a, b)` (the smaller addend)
3. `total_amount = c` (the sum)

**Triplet selection scoring** (when multiple triplets exist):
- +3 if total value appears near "total/due/grand/payable/amount" label
- +3 if tax value appears near "tax/vat/gst/ast/sales" label
- +2 if subtotal value appears near "subtotal/subtotat/net charges/retainer/services/order" label
- +1 if tax < subtotal (tax is usually smaller)
- +2 if tax rate is plausible (3%–30%)

**Fallback extraction** (if no triplet):
- Search for explicit total patterns: `grand total`, `total due`, `payable total`, `amount due`, etc.
- Search for explicit tax patterns: `vat`, `tax`, `sales tax`, `gst`, etc.
- Search for subtotal patterns: `subtotal`, `net charges`, etc.

**Mathematical cross-validation**:
- If subtotal and total exist but no VAT: `vat = total - subtotal`
- If subtotal and VAT exist but no total: `total = subtotal + vat`
- If all three exist but `subtotal + vat ≠ total` (within 0.05): trust the math, adjust total

### Summary CSV Generation

Write CSV with columns: `filename`, `total_amount`, `vat_amount`

- One row per invoice with extracted values formatted to 2 decimal places
- Final row with `filename=total` and sums of numeric columns

### File Operations

1. Create output directories: `/app/invoices/`, `/app/other/`
2. For each document:
   - Classify as invoice or other
   - Move to appropriate directory using `shutil.move()`
3. Verify `/app/documents/` is empty after processing

## Robustness to Spec Variations

### document_content_patterns
- Golden triplet detection works regardless of document title
- Disclaimer patterns catch edge cases (receipts, POs, reminders, reimbursements)
- Fallback keyword matching handles documents where OCR destroyed numbers

### document_modality_and_ocr_noise
- Multiple OCR passes with different PSM modes maximize text capture
- Comma normalization handles varied number formatting
- Simple amount pattern `(\d+(?:\.\d{1,2})?)` is robust to OCR artifacts
- Mathematical cross-validation repairs OCR errors in individual fields

### financial_field_expression
- Golden triplet doesn't rely on field labels at all
- Label-based scoring is only a tiebreaker when multiple triplets exist
- Fallback patterns cover common labels: total, amount due, grand total, VAT, tax, GST, subtotal, net charges
- Mathematical inference recovers missing fields (vat = total - subtotal)

### batch_scale_and_class_balance
- Algorithm is O(n) per document for classification
- Golden triplet detection is O(m³) where m is number of unique amounts (typically small)
- Scales to any batch size
- Works for invoice-heavy or other-heavy mixes

## Common Pitfalls and Solutions

### Pitfall 1: Regex alternation ordering
**Problem**: Pattern `\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?` matches "105" from "1058.40" then "8.40" separately.

**Solution**: Normalize text by stripping commas first, then use simple pattern `(\d+(?:\.\d{1,2})?)`.

### Pitfall 2: Title-based classification
**Problem**: "Remittance Notice" sounds like a payment confirmation but has full invoice structure. "Payment Reminder" has amounts but explicitly disclaims invoice status.

**Solution**: Use mathematical structure (golden triplet) as primary signal, disclaimers as override. Never classify based on title alone.

### Pitfall 3: OCR noise in numbers
**Problem**: "VAT Inctuded 483" should be "4.83" but OCR dropped decimal point.

**Solution**: Mathematical cross-validation. If subtotal=49.27 and total=54.10, then vat=54.10-49.27=4.83, not 483.

### Pitfall 4: Receipt vs Invoice
**Problem**: Receipts have amounts and may even form golden triplets, but they confirm payment already made, not demand payment.

**Solution**: Detect receipt signals: "card payment approved", "total paid", "receipt" (with OCR variants). These override golden triplets.

### Pitfall 5: Purchase Order vs Invoice
**Problem**: POs have subtotal + tax + total structure (golden triplet exists) but are pre-transaction requests, not billing documents.

**Solution**: Detect PO signals: "purchase order", "approval status: pending", "approved spend ceiling". These override golden triplets.

## Testing Checklist

When processing a new batch, verify:
- [ ] All PDFs and images in `/app/documents/` are processed
- [ ] `/app/documents/` is empty after processing
- [ ] Invoices are in `/app/invoices/` with correct `total_amount` and `vat_amount`
- [ ] Non-invoices are in `/app/other/`
- [ ] `summary.csv` has correct columns: `filename`, `total_amount`, `vat_amount`
- [ ] `summary.csv` has one row per invoice plus a `total` row
- [ ] Numeric values in `summary.csv` are formatted to 2 decimal places
- [ ] Sums in `total` row match the sum of invoice rows
- [ ] Mathematical consistency: for each invoice, `subtotal + vat ≈ total`

## Reference Implementation

See `process.py` in the task environment for a complete working implementation of this methodology.
