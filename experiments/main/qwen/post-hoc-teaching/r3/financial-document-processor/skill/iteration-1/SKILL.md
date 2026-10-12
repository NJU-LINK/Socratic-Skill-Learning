---
name: financial-document-processor
description: >
  Classify mixed batches of financial documents (PDFs and images) as invoice or
  other, extract total_amount and vat_amount from invoices, move files to
  designated directories, and produce a summary CSV with per-invoice rows and a
  totals row. Handles noisy OCR, varied document titles, multiple financial
  field expression styles, and arbitrary batch sizes.
---

# Financial Document Processor

## Purpose

Process a mixed batch of business documents in `/app/documents/`:
1. Classify each PDF/JPG as `invoice` or `other` based on content
2. Move invoices to `/app/invoices/`, non-invoices to `/app/other/`
3. Extract `total_amount` (final amount including tax) and `vat_amount` from each invoice
4. Write `/app/invoices/summary.csv` with one row per invoice plus a `total` row
5. Leave `/app/documents/` empty after processing

## Execution

Run the processing script:

```bash
python3 /skill/scripts/process_documents.py
```

The script is self-contained and requires only the Python standard library plus:
- `pytesseract` and `Pillow` (for image OCR)
- `fitz` (PyMuPDF, fallback PDF text extraction)
- `pdftotext` CLI tool (primary PDF extraction)

All of these are pre-installed in the task environment.

## Architecture: Multi-Candidate Pipeline

The pipeline is designed around a key insight: **different OCR passes produce different readable fields**. Rather than collapsing to a single text and hoping, the pipeline:

1. **Generate**: Collect ALL OCR candidate texts (multiple PSM modes × multiple preprocessing variants)
2. **Classify**: Run classification on EVERY candidate, use the maximum invoice score
3. **Extract**: Run field extraction on EVERY candidate, collect all values per field, select best by label priority

This decouples field extraction from OCR-selection heuristics and exploits the diversity of OCR outputs.

### Why not "longest text wins"?

The longest OCR output maximizes total character count, not field legibility. A longer text may have a complete header but garble the line containing the VAT amount. A shorter text might have those critical lines perfectly. By extracting from all candidates and selecting per-field, we get the best of each.

## Classification Logic

### What is an invoice?

An **invoice** is a seller-to-buyer document requesting payment for goods or services rendered. Key characteristics:
- Identifies seller and buyer (client, customer, bill to, ship to)
- Lists items/services with prices
- Shows tax/VAT/GST amounts
- States a total amount due
- Uses payment-request language ("amount due", "please remit", "total due")

### What is NOT an invoice?

Common non-invoice financial documents:
- **Receipts**: Confirm payment already made ("receipt", "card payment approved", "total paid")
- **Payment reminders**: Reference existing outstanding balances ("payment reminder", "outstanding balance", "this notice is not a tax invoice")
- **Purchase orders**: Buyer's request to purchase, not yet approved ("purchase order", "approval status: pending")
- **Expense reimbursement summaries**: Internal employee expense reports ("expense reimbursement", "approved meals", "reclaimable tax")

### Classification approach

The classifier uses a **scoring system with hard negative overrides**, applied to each OCR text independently:

1. **Hard negative checks** (immediate `other` classification, score = -50):
   - Explicit disclaimer: "not a tax invoice" / "not an invoice"
   - Receipt signals (≥2): receipt title + payment confirmed/paid
   - Expense/reimbursement signals (≥1): expense reimbursement title, approved employee items
   - Purchase order signals (≥2): PO title + pending status or spend ceiling
   - Payment reminder signals (≥2): reminder title + outstanding balance/prior amounts

2. **Positive scoring** for invoice classification (threshold ≥4):
   - Title matches: "invoice" (+3), "billing statement" (+3), "charge note" (+3), "tax invoice" (+3)
   - Fuzzy title matches for OCR noise: "charge n[a-z]{2,4}" (+2), "invo[a-z]{2,4}" (+2)
   - Billing document titles: "tax document" (+2), "remittance notice" (+2), "bill to" (+2)
   - Payment request language: "amount due" (+2), "total due" (+2), "grand total" (+2), "payable total" (+2), "please remit" (+2)
   - Service/item indicators: "consulting services" (+1), "freight services" (+1), "hardware order" (+1), "client:" (+1), "customer:" (+1)
   - Financial structure: subtotal + tax present (+1), VAT with amount (+1)

3. **Fallback** (score 2-3): If document has ≥2 monetary amounts and either a date or reference number, classify as invoice.

**Multi-text aggregation**: The final classification is the one with the maximum score across all OCR candidates. This means if ANY OCR pass reveals invoice signals that others miss, the document is still classified correctly.

### Handling OCR noise

Image OCR (Tesseract) produces noisy output. The script mitigates this by:
- Running 5 PSM modes (3, 4, 6, 11, 12) on 4 image variants (original, grayscale, contrast-enhanced, sharpened) = up to 20 OCR passes
- Deduplicating results
- Using fuzzy regex patterns for known OCR confusions (e.g., "Charge Nate" for "Charge Note")
- Matching OCR-garbled variants of key labels (e.g., "total d[uo]e" for "total due")
- Classifying each text independently and taking the max score

## Financial Field Extraction

### Multi-text extraction

Field extraction runs on EVERY OCR candidate text. For each field, all candidate values are collected with their label priority rank. The best value per field is selected by:
- **Priority rank** (lower = higher priority): more specific labels win
- **Amount** (descending for ties): larger values preferred when labels are equal

### Total amount extraction

Priority-ordered pattern matching:
1. **Priority 1 (high)**: "grand total", "amount due", "total due", "payable total", "balance due"
2. **Priority 2 (medium)**: "invoice total", "total amount", "amount payable"
3. **Priority 3 (low)**: Generic "total" — **tightened** to require colon/dash separator and line-start or whitespace boundary, avoiding false matches on "subtotal", "total tax", "total paid", etc.

Handles OCR noise in labels and currency symbols (£, $, €).

### VAT/tax amount extraction

Priority-ordered pattern matching:
1. **Priority 1**: VAT/GST with explicit rate (e.g., "VAT 10%: 128.00")
2. **Priority 2**: VAT/GST/Tax with separator (colon, dash)
3. **Priority 3**: VAT/GST/Tax without separator, OCR-garbled variants ("@st", "ast", "st.")
4. **Priority 4**: No-decimal OCR fallback (e.g., "ast 7840" → 78.40, interpreting last 2 digits as decimal)

### Fallback calculation

If no explicit VAT field is found but both subtotal and total are present:
```
vat_amount = total_amount - subtotal
```

## Output Format

`summary.csv` has exactly three columns:
```csv
filename,total_amount,vat_amount
doc1.pdf,751.68,55.68
doc2.jpg,1058.40,78.40
total,1810.08,134.08
```

- One row per invoice (filename = original opaque filename)
- Final row with `filename` = "total" and summed numeric columns
- Amounts formatted as decimal numbers with 2 decimal places
- Non-invoice documents are excluded from the CSV

## Variation Handling

### document_content_patterns
- Recognizes diverse invoice titles: invoice, billing statement, charge note, tax document, remittance notice, tax invoice
- Recognizes diverse non-invoice types: receipt, payment reminder, purchase order, expense reimbursement
- Uses content-based classification rather than filename-based
- Multi-text classification ensures weak or OCR-garbled markers are still detected

### document_modality_and_ocr_noise
- PDFs: Uses pdftotext (primary) with PyMuPDF fallback
- Images: Multi-strategy OCR with 4 preprocessing variants × 5 PSM modes = up to 20 candidates
- Fuzzy pattern matching for garbled text
- Field extraction runs on ALL candidates, not just the longest
- Per-field selection by label priority, not text selection

### financial_field_expression
- Handles labels: Total, Amount Due, Grand Total, Payable Total, Total Due, Balance Due
- Handles tax labels: VAT, Tax, GST, Sales Tax, with optional rate percentages
- Handles numeric formats: commas, currency symbols, various decimal separators
- No-decimal OCR fallback for garbled tax amounts
- Calculates tax from subtotal when explicit tax field is absent

### batch_scale_and_class_balance
- Processes any number of documents (small or large batches)
- Correctly handles invoice-heavy or other-heavy mixes
- Summary totals are computed dynamically from actual invoice rows
- Works with any ratio of invoices to non-invoices
