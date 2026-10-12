---
name: financial-document-processor
description: >
  Process mixed batches of business documents (PDFs and images) by classifying
  each as invoice or non-invoice, extracting financial fields (total_amount,
  vat_amount) from invoices, routing files to appropriate directories, and
  producing a summary CSV. Handles noisy OCR, varied document types with
  overlapping financial vocabulary, multiple numeric formats, and arbitrary
  batch sizes.
---

# Financial Document Processor

## Task Overview

Given a directory of mixed business documents with opaque filenames:
1. Extract text from each document (PDF via `pdftotext`/PyMuPDF, images via `tesseract`/`pytesseract`)
2. Classify each as `invoice` or `other` based on content
3. Move invoices to `/app/invoices/`, non-invoices to `/app/other/`
4. Extract `total_amount` (final amount including tax) and `vat_amount` (tax/VAT/GST) from each invoice
5. Write `/app/invoices/summary.csv` with columns `filename`, `total_amount`, `vat_amount`, plus a final `total` row with column sums

## Architecture

The processing pipeline has four stages:

```
Documents → Text Extraction → Classification → Field Extraction → File Routing + CSV
```

Run the provided script: `python3 /skill/process_documents.py`

Or implement inline following the methods below.

## Stage 1: Text Extraction

### PDFs
- **Primary**: `pdftotext file.pdf -` (fast, clean for text-based PDFs)
- **Fallback**: PyMuPDF (`fitz.open(file).pages[].get_text()`)
- **Last resort**: Render pages to images at 300 DPI, then OCR

### Images (JPG/PNG/etc.)
- Use `pytesseract` with **multiple PSM modes** (6, 4, 3, 11, 12) — different modes capture different text regions
- Apply **contrast enhancement** (2x) + sharpening, then re-OCR
- **Combine all OCR results** into a single text blob — different modes/enhancements capture different parts of noisy documents
- This multi-strategy approach is critical for handling OCR noise variation

### Key Principle
OCR output is inherently noisy. Never rely on a single extraction pass. Combine results from multiple strategies to maximize information capture.

## Stage 2: Document Classification

### Strategy: Weighted Scoring with Override Rules

**Step 1: Check strong non-invoice signals** (immediate rejection):
- Explicit disclaimers: "not a tax invoice", "this notice is not"
- Document types: "purchase order", "payment reminder", "expense reimbursement"
- Status markers: "approval status: pending", "approved spend ceiling"
- **Receipt signals**: "card payment approved" (with OCR variants), "payment approved"

**Step 2: Score-based classification** using weighted keyword patterns:

| Signal Type | Examples | Weight |
|---|---|---|
| Title: invoice-like | "invoice", "charge note", "tax document", "billing statement" | +3 to +5 |
| Title: non-invoice | "purchase order", "payment reminder", "expense reimbursement", "receipt" | -3 to -5 |
| Body: strong invoice | "amount due", "total due", "grand total", "payable total", "please remit" | +2 to +3 |
| Body: moderate invoice | "vat", "gst", "sales tax", "subtotal", "bill to", "customer:" | +1 |
| Body: non-invoice | "reminder", "outstanding balance", "reimbursement", "employee:", "reclaimable", "total paid", "receipt" | -2 to -3 |

**Compound signals** (title + body combination):
- "Tax Document" + "remit"/"grand total" → invoice
- "Billing Statement" + "amount due" → invoice
- "Remittance Notice" + "payable total"/"sales tax" → invoice

**Classification boundary**: score > 0 → invoice, else → other

### Key Distinctions
- **Invoices** ARE: formal billing documents requesting payment — "invoice", "billing statement", "charge note", "tax document" (with payment request), "remittance notice" (with payable total)
- **Receipts** are NOT invoices: a receipt is proof of payment already made (e.g., store receipt from "Lakeside Cafe" with "Card Payment Approved", "Total Paid")
- **Payment reminders** are NOT invoices (they reference an existing invoice)
- **Purchase orders** are NOT invoices (they request goods, not payment)
- **Expense reimbursement summaries** are NOT invoices (internal documents)

**Key signals that a document is NOT an invoice:**
- "Receipt" in title or body
- "Card Payment Approved" / "Payment Approved"
- "Total Paid" (past tense — payment already made)
- Store/cafe/restaurant names with receipt-style formatting

## Stage 3: Financial Field Extraction

### CRITICAL: Two-Tier Extraction with OCR Noise Recovery

OCR frequently drops decimal points from numbers. This is the most dangerous failure mode because it produces plausible-looking but wrong values. The extraction MUST handle this.

**Example**: A receipt with subtotal=49.27, VAT=4.89, total=54.20 may OCR as:
- Subtotal: `"49.27"` (decimal preserved ✓)
- VAT: `"489"` (decimal dropped ✗)
- Total: `"5420"` (decimal dropped ✗)

If you only use decimal-requiring regex patterns, total will be `None` and you'll silently write `0.00` to the CSV, corrupting the summary totals.

### Tier 1: Decimal Amount Extraction (High Confidence)

Use regex patterns that require a literal decimal point:
```
AMOUNT_DECIMAL = r'(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{1,2})'
```

This handles both comma-separated (`1,280.00`) and plain (`1058.40`) formats.

**Total patterns** (priority-ordered):
1. Explicit labels: `grand total`, `total due`, `amount due`, `payable total`, `total paid`
2. OCR-noisy variants: `otal due`, `otal paid`, `otal pet`, `eal due`
3. Generic: `total` followed by amount on same line

**VAT patterns** (priority-ordered):
1. `VAT included` / `VAT inc` (with OCR variants: `nctuded`, `inetuded`)
2. Explicit: `VAT`, `GST`, `Sales Tax` followed by amount
3. `Tax` label (excluding: "no tax", "prior tax", "estimated tax")
4. OCR-noisy: `ast`, `est`, `st` followed by amount

### Tier 2: Integer Amount Extraction (OCR Noise Recovery)

When Tier 1 fails (typically for total or VAT), extract **integer-only amounts** from lines with financial labels:

1. Scan each line for financial label keywords (total, vat, tax, subtotal, due, etc.)
2. If a line has a label AND an integer (no decimal point), capture it as a candidate
3. Filter out years (1900-2099), reference numbers, and dates
4. Generate all **decimal insertion variants** for each integer:
   - `5420` → `[5.420, 54.20, 542.0]`
   - `489` → `[4.89, 48.9]`

### Simultaneous Multi-Value Recovery

When **both** total and VAT have dropped decimals, you must try all combinations simultaneously:

```
For each subtotal candidate S:
  For each total variant T:
    For each VAT variant V:
      error = |T - (S + V)|
      if error < tolerance (e.g., 2.0):
        record (T, V, error)
Select the combination with lowest error
```

**Example** with subtotal=49.27, total_int=5420, vat_int=489:
- Try T=54.20, V=4.89: |54.20 - (49.27 + 4.89)| = |54.20 - 54.16| = 0.04 ✓ **BEST**
- Try T=54.20, V=48.9: |54.20 - (49.27 + 48.9)| = 43.97 ✗
- Try T=542.0, V=4.89: |542.0 - 54.16| = 487.84 ✗

### Fallback Strategies
- If total not found but subtotal + vat exist: `total = subtotal + vat`
- If vat not found but total and subtotal exist: `vat = total - subtotal`
- If nothing found: use the largest decimal amount in the document as total

### Candidate Selection When No Subtotal Available

When multiple total/VAT candidates exist and no subtotal is available for arithmetic validation, use **frequency** as the primary signal: correct values appear consistently across multiple OCR passes while OCR errors are sporadic. Combine frequency with ratio heuristic (vat/total should be 1-50%) as tiebreaker.

### NEVER Silently Default to 0.0

If extraction fails for an invoice, do NOT write `0.00` — this corrupts the summary totals. Instead:
- Use the best available partial result
- Log a warning
- Only use 0.0 as absolute last resort when all extraction strategies fail

## Stage 4: File Operations and CSV Output

### Directory Setup
```python
os.makedirs("/app/invoices", exist_ok=True)
os.makedirs("/app/other", exist_ok=True)
```

### File Movement
- Use `shutil.move()` to preserve files (not copy+delete)
- Move to `/app/invoices/` or `/app/other/` based on classification
- `/app/documents/` must be empty after processing

### CSV Format
```csv
filename,total_amount,vat_amount
doc1.pdf,751.68,55.68
doc2.jpg,1058.40,78.40
total,1810.08,134.08
```

- Exactly three columns: `filename`, `total_amount`, `vat_amount`
- One row per invoice (not non-invoices)
- Final row: `filename` = `total`, numeric columns = sums
- Amounts formatted to 2 decimal places

## Variation Dimensions

### document_content_patterns
- Documents signal identity through content, not filenames
- Handle weak/non-standard invoice markers
- Handle overlapping financial vocabulary between invoices and non-invoices
- Classification cues may span multiple text regions

### document_modality_and_ocr_noise
- Mix of PDF (text-based and scanned) and image files
- Noisy OCR: garbled labels, dropped characters, **missing decimal points**
- Multi-strategy OCR extraction is essential
- Key fields may be only partially legible and must be inferred from imperfect extraction
- **Integer-only OCR amounts must be recovered via arithmetic validation**

### financial_field_expression
- Total labels: Total, Amount Due, Grand Total, Total Due, Payable Total, Total Paid
- Tax labels: VAT, Tax, GST, Sales Tax, VAT included
- Numeric formats: comma-separated, plain, various decimal conventions
- Taxes may need recovery from subtotals or rate calculations
- Multiple amount candidates may exist; select the correct one via arithmetic validation

### batch_scale_and_class_balance
- Arbitrary number of documents (small to large batches)
- Any ratio of invoices to non-invoices
- Summary totals must be correct regardless of batch composition

## Implementation Notes

### Available Tools (typical environment)
- `pdftotext` (poppler-utils)
- `tesseract` (command-line OCR)
- Python: `pytesseract`, `PIL/Pillow`, `PyMuPDF` (fitz)
- Standard library: `os`, `re`, `csv`, `shutil`, `subprocess`

### Robustness Checklist
- [ ] Handle both comma-separated and plain number formats
- [ ] Try multiple OCR PSM modes and combine results
- [ ] **Two-tier extraction: decimal patterns first, then integer recovery**
- [ ] **Simultaneous multi-value arithmetic validation for OCR noise**
- [ ] Check strong non-invoice signals before scoring
- [ ] **Distinguish receipts (proof of payment) from invoices (payment requests)**
- [ ] Handle documents where text extraction fails (route to other)
- [ ] Ensure documents directory is empty after processing
- [ ] Format all amounts to exactly 2 decimal places in CSV
- [ ] **Never silently write 0.00 for failed extraction**
- [ ] **Use frequency-based candidate selection when no subtotal available**
