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
   - Weaker title matches: "bill from" (+2), "payment request" (+2), "fee schedule/statement/notice" (+2), "statement of charges/fees/account" (+2)
   - Fuzzy title matches for OCR noise: "charge n[a-z]{2,4}" (+2), "invo[a-z]{2,4}" (+2)
   - Billing document titles: "tax document" (+2), "remittance notice" (+2), "bill to" (+2)
   - Payment request language: "amount due" (+2), "total due" (+2), "grand total" (+2), "payable total" (+2), "please remit" (+2)
   - Service/item indicators: "consulting services" (+1), "freight services" (+1), "hardware order" (+1), "professional fees" (+1), "management fees" (+1), "support charges" (+1), "client:" (+1), "customer:" (+1), "vendor:" (+1), "supplier:" (+1)
   - Financial structure: subtotal + tax present (+1), VAT with amount (+1), subtotal present (+1), "Total:" at line start (+1)
   - Invoice number patterns: "invoice #/no/number/ref" (+2), "INV-xxx" (+2), international variants like "Rechnungsnr", "Facture no" (+2)

3. **Fallback** (score 2-3): If document has ≥2 monetary amounts and either a date or reference number, classify as invoice.

**Multi-text aggregation**: The final classification is the one with the maximum score across all OCR candidates. This means if ANY OCR pass reveals invoice signals that others miss, the document is still classified correctly.

### Handling OCR noise

Image OCR (Tesseract) produces noisy output. The script mitigates this by:
- Running 5 PSM modes (3, 4, 6, 11, 12) on 4 image variants (original, grayscale, contrast-enhanced, sharpened) = up to 20 OCR passes
- Deduplicating results
- Using fuzzy regex patterns for known OCR confusions (e.g., "Charge Nate" for "Charge Note")
- Matching OCR-garbled variants of key labels (e.g., "total d[uo]e" for "total due")
- Classifying each text independently and taking the max score

**Scanned PDFs**: When a PDF contains no extractable text (scanned/image-based), the system automatically renders each page to an image at 300 DPI and runs the same multi-strategy OCR pipeline. This handles the full spectrum from text-based PDFs to fully scanned documents to mixed PDFs with some text and some scanned pages.

## Financial Field Extraction

### Format-aware number parsing

The pipeline detects whether a document uses US or European number format:
- **US format**: `1,234.56` (comma=grouping, period=decimal)
- **European format**: `1.234,56` (period=grouping, comma=decimal)

Detection counts format signals across all OCR texts and selects the dominant format. All amount extraction and parsing then uses format-specific patterns:
- US capture: `([\d,]+(?:\.\d+)?)` 
- EU capture: `([\d.]+(?:,\d+)?)`
- `parse_amount(text, fmt)` strips the appropriate grouping separator and normalizes the decimal separator

This prevents silent truncation of European-format amounts (e.g., "234,56" → 234.56, not 234).

### Multi-strategy extraction with consistency checks

Field extraction runs on EVERY OCR candidate text. For each field, all candidate values are collected with their label priority rank. Selection uses multiple strategies:

1. **Priority-based selection**: For each field, prefer the match with the highest-priority (most specific) label
2. **Consistency check**: When multiple total candidates exist, prefer the one that equals subtotal + VAT (within rounding tolerance)
3. **Fallback calculations**: If no explicit VAT found:
   - Calculate from subtotal: vat = total - subtotal
   - Calculate from rate: vat = subtotal × (rate / 100)

### Total amount extraction

Priority-ordered pattern matching:
1. **Priority 1 (high)**: "grand total", "amount due", "total due", "payable total", "balance due"
2. **Priority 2 (medium)**: "invoice total", "total amount", "amount payable"
3. **Priority 3 (low)**: Generic "total" — **tightened** to require colon/dash separator and line-start or whitespace boundary, avoiding false matches on "subtotal", "total tax", "total paid", etc.

When multiple total candidates exist across OCR texts, the consistency check selects the one matching subtotal + VAT.

### VAT/tax amount extraction

Priority-ordered pattern matching:
1. **Priority 1**: VAT/GST with explicit rate (e.g., "VAT 10%: 128.00")
2. **Priority 2**: VAT/GST/Tax with separator (colon, dash)
3. **Priority 3**: VAT/GST/Tax without separator, OCR-garbled variants ("@st", "ast", "st.")
4. **Priority 4**: No-decimal OCR fallback (e.g., "ast 7840" → 78.40, interpreting last 2 digits as decimal)

### Tax rate extraction and calculation

When an explicit VAT/tax amount is not found, the system can:
1. Extract tax rate percentages (e.g., "VAT 10%", "GST 20%", "Tax @ 15%")
2. Calculate tax = subtotal × (rate / 100)
3. This handles invoices where the tax amount is implied by the rate rather than stated explicitly

### Fallback calculation chain

If no explicit VAT field is found:
1. Try: vat = total - subtotal (direct subtraction)
2. Try: vat = subtotal × (rate / 100) (rate-based calculation)
3. If total was also not found but subtotal and rate are available: total = subtotal + calculated_vat

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
- Recognizes weaker invoice markers: bill from, payment request, fee schedule/notice, statement of charges
- Recognizes invoice number patterns: INV-xxx, invoice #/no/ref, international variants (Rechnungsnr, Facture no, Factuur nr, Fattura n)
- Recognizes diverse non-invoice types: receipt, payment reminder, purchase order, expense reimbursement
- Uses content-based classification rather than filename-based
- Multi-text classification ensures weak or OCR-garbled markers are still detected
- Broader service/item indicators: professional fees, management fees, support charges, vendor/supplier labels
- Format-agnostic financial structure detection: recognizes amounts in both US and European conventions

### document_modality_and_ocr_noise
- PDFs: Uses pdftotext (primary) with PyMuPDF fallback
- **Scanned PDFs**: When text extraction yields insufficient text, automatically renders PDF pages to images at 300 DPI and runs OCR
- **Mixed PDFs**: Handles PDFs with both embedded text and scanned/image-based pages
- Images: Multi-strategy OCR with 4 preprocessing variants × 5 PSM modes = up to 20 candidates
- Fuzzy pattern matching for garbled text
- Field extraction runs on ALL candidates, not just the longest
- Per-field selection by label priority, not text selection

### financial_field_expression
- Handles labels: Total, Amount Due, Grand Total, Payable Total, Total Due, Balance Due
- Handles tax labels: VAT, Tax, GST, Sales Tax, with optional rate percentages
- **Format-aware parsing**: detects US (1,234.56) vs European (1.234,56) format per document
- Handles numeric formats: commas, periods, currency symbols in both conventions
- No-decimal OCR fallback for garbled tax amounts
- **Tax from rate**: extracts rate percentages (e.g., "VAT 10%") and calculates tax = subtotal × rate
- **Consistency-based selection**: when multiple total candidates exist, prefers the one matching subtotal + VAT
- **Fallback calculation chain**: total - subtotal → rate × subtotal → total reconstruction
- Handles invoices with multiple plausible amount candidates across sections
- **Anchored "total" pattern**: low-priority generic "total" requires line-start anchor to avoid matching "Line Total"

### batch_scale_and_class_balance
- Processes any number of documents (small or large batches)
- Correctly handles invoice-heavy or other-heavy mixes
- Summary totals are computed dynamically from actual invoice rows
- Works with any ratio of invoices to non-invoices
