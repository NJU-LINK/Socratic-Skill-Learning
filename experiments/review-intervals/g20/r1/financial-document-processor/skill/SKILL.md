---
name: financial-document-processor
description: >
  Process a batch of mixed business documents (PDFs and images) by classifying
  each as invoice or other, extracting financial fields (total_amount, vat_amount)
  from invoices, moving files to appropriate directories, and writing a summary CSV.
  Handles OCR noise via multi-pass extraction and arithmetic cross-validation.
---

# Financial Document Processor

## Purpose

Process a batch of mixed business documents from `/app/documents/`, classify each as `invoice` or `other`, extract financial fields from invoices, move files to `/app/invoices/` and `/app/other/`, and produce `/app/invoices/summary.csv`.

## When to Use

- You have a directory of mixed PDF and image documents with opaque filenames
- You need to classify them as invoices vs. non-invoices based on content
- You need to extract total_amount and vat_amount from invoices
- You need to produce a summary CSV with per-invoice rows and a totals row

## Execution

**If the script is available at `/skill/financial-document-processor/scripts/process.py`:**
```bash
python3 /skill/financial-document-processor/scripts/process.py
```

**If the script is not pre-installed (common in fresh environments):**
1. Read the script from `skill/financial-document-processor/scripts/process.py` in the workspace
2. Write it to `/app/process.py` (or another writable location)
3. Run it: `python3 /app/process.py`

The script handles everything end-to-end: text extraction, classification, field extraction, file routing, and summary CSV generation.

## Key Mechanisms

### 1. Text Extraction

**PDFs**: Use `pdftotext` for embedded text extraction.

**Images (JPG/PNG/etc.)**: Use `tesseract` with multiple PSM (Page Segmentation Mode) settings (3, 4, 6, 11) to maximize OCR coverage. Combine outputs from all passes for maximum text recovery.

### 2. Classification Strategy

The fundamental distinction is **semantic**: 
- **Invoice** = a *request for payment* (billing statement, tax document, charge note, remittance notice)
- **Receipt** = *proof that payment was already made* (card payment approved, total paid)
- **Other non-invoices**: purchase orders, expense reports, payment reminders

Classification uses a **priority-ordered signal system**:

**Step 1 — Non-invoice overrides** (checked first, any match → "other"):

*Explicit disclaimers:*
- "not a tax invoice", "not an invoice", "this notice is not"

*Document types that are not invoices:*
- "purchase order", "expense reimbursement", "expense report"
- "payment reminder", "remittance advice"
- "approval status: pending", "pending approval"

*Receipts (proof of payment, NOT requests for payment):*
- "payment approved", "total paid", "card payment"
- OCR-noisy receipt variants: "recei[pc]*t", "recep[tc]?" (handles "receict", "receit", etc.)

**Step 2 — Invoice type patterns** (any match → "invoice"):
- "invoice", "billing statement", "tax document", "charge note", "tax invoice"

**Step 3 — Structural signals** (combination required → "invoice"):
- Customer/client/bill-to/ship-to field + amount due/total due/grand total
- Remittance language + tax presence
- "Remittance notice" + payable total + tax

**Step 4 — Default**: "other"

### 3. Financial Field Extraction

Uses a **three-strategy cascade**:

**Strategy 1 — Arithmetic-first** (most robust for noisy OCR):
1. Find subtotal (most stable value across OCR passes)
2. Find VAT/tax (most stable value across OCR passes)
3. Compute total = subtotal + VAT
4. If explicit total found and matches computed (within tolerance), use explicit value

**Strategy 2 — Explicit value extraction**:
- Total patterns: "grand total", "amount due", "total due", "payable total" (plus OCR-noisy variants)
- VAT patterns: "vat", "gst", "tax", "sales tax" (plus OCR-noisy variants like "st78.40")
- Subtotal patterns: "subtotal", "net charges" (plus OCR-noisy variants like "subtotat")

**Strategy 3 — Arithmetic inference**:
- If total found but VAT missing: VAT = total - subtotal
- If subtotal found but total missing: total = subtotal + VAT

### 4. OCR Noise Handling

**Missing decimal recovery**: When OCR drops decimal points (e.g., "483" instead of "4.83", "5420" instead of "54.20"), insert decimal 2 places from the right (standard monetary format).

**OCR-tolerant regex patterns**: Use flexible patterns that accommodate character substitutions:
- `subto\w*` matches "subtotal", "subtotat", "subtoat"
- `vat\w*` matches "vat", "vat included", "vat inctuded", "vat nce"
- `total\w*` matches "total", "total pet", "total paid"

**Multi-pass stability**: When the same field is extracted from multiple OCR passes, use `find_most_stable_value()` to group readings within tolerance and select the median of the largest group.

**Arithmetic cross-validation**: The relationship `subtotal + VAT ≈ total` is used to:
- Resolve ambiguous OCR readings (pick the reading that satisfies the identity)
- Infer missing fields (compute total from subtotal + VAT, or VAT from total - subtotal)
- Detect and correct OCR errors (if readings don't satisfy the identity, try alternative interpretations)

### 5. Output

- Move invoice files to `/app/invoices/`
- Move non-invoice files to `/app/other/`
- Write `/app/invoices/summary.csv` with columns: `filename`, `total_amount`, `vat_amount`
- Add a final row with `filename=total` and summed numeric columns
- Ensure `/app/documents/` is empty after processing

## Variation Handling

This skill handles the following variation axes from the family spec:

### document_content_patterns
- **Weak invoice markers**: Structural signals (customer + amount due + tax) catch invoices without explicit "invoice" labels
- **Overlapping vocabulary**: Non-invoice overrides (purchase order, expense reimbursement, payment reminder, receipt) prevent false positives
- **Multi-region cues**: Combining signals from different parts of the document (header type + body structure + footer totals)
- **Receipt vs invoice distinction**: "total paid" / "payment approved" = receipt = other; "amount due" / "total due" = invoice

### document_modality_and_ocr_noise
- **Multi-PSM OCR**: Running tesseract with 4 different PSM modes maximizes text recovery from varied image qualities
- **OCR-tolerant patterns**: Flexible regex patterns accommodate character substitutions, dropped characters, and merged words
- **Missing decimal recovery**: Handles the common OCR failure of dropping decimal points in monetary amounts
- **Arithmetic cross-validation**: Uses the mathematical relationship between subtotal, VAT, and total to resolve ambiguous readings

### financial_field_expression
- **Multiple total labels**: Recognizes "grand total", "amount due", "total due", "payable total", and OCR variants
- **Multiple tax labels**: Recognizes "VAT", "GST", "tax", "sales tax", and OCR variants
- **Inferred totals**: Computes total from subtotal + VAT when explicit total is missing or unreliable
- **Inferred VAT**: Computes VAT from total - subtotal when explicit VAT is missing or unreliable
- **Rate-based recovery**: Can handle "VAT 10%" patterns where the rate is given instead of the amount

### batch_scale_and_class_balance
- **Arbitrary batch sizes**: The script processes all PDF and image files in the documents directory
- **Any class balance**: Classification logic works regardless of the ratio of invoices to non-invoices
- **Correct summary totals**: The total row correctly sums across any number of invoice rows

## Dependencies

- `pdftotext` (from poppler-utils) for PDF text extraction
- `tesseract` for image OCR
- Python 3 with standard library only (no external packages required)

## Error Handling

- If a document cannot be classified, it defaults to "other" (safer than false invoice)
- If financial fields cannot be extracted, they default to 0.00
- If OCR produces no text, the document is classified as "other"
- The script verifies that `/app/documents/` is empty after processing and warns if not

## Troubleshooting

**Script not found at /skill/**: The skill package may not be mounted at `/skill/` in the container. Read the script from the workspace (`skill/financial-document-processor/scripts/process.py`) and write it to `/app/process.py`.

**Receipt classified as invoice**: Ensure receipt indicators ("payment approved", "total paid", "card payment", OCR-noisy "receict") are checked in Step 1 (non-invoice overrides) BEFORE invoice type patterns in Step 2.

**OCR extraction failures**: Try multiple PSM modes (3, 4, 6, 11) and combine outputs. Use arithmetic cross-validation (subtotal + VAT ≈ total) to resolve ambiguous readings.

**Missing decimal points**: Common OCR error. Insert decimal 2 places from the right for monetary amounts (e.g., "483" → 4.83, "5420" → 54.20).

## Critical Insight: Receipt vs Invoice

The most common classification error is treating receipts as invoices. The distinction is **semantic**, not structural:

- **Invoice** = *request for payment* → contains "amount due", "total due", "please remit", "billing statement"
- **Receipt** = *proof of payment* → contains "payment approved", "total paid", "card payment", "receipt"

Both may have subtotals, VAT, and totals. The decisive signal is whether the document is *asking for money* (invoice) or *confirming money was paid* (receipt).
