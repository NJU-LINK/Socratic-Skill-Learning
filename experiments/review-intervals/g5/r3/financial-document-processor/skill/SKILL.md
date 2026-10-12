---
name: financial-document-processor
description: >
  Process a mixed batch of business documents (PDFs and images) by classifying
  each as invoice or other, extracting financial amounts (total_amount,
  vat_amount) from invoices, routing files to appropriate directories, and
  generating a summary CSV with per-invoice rows and a totals row. Handles
  noisy OCR, multiple document types, fuzzy classification signals, and
  varied numeric conventions.
---

# Financial Document Processor

## Task Template

Process a mixed batch of business documents (PDFs and images) by:
1. Classifying each document as `invoice` or `other` based on content
2. Extracting financial amounts from invoices (total_amount, vat_amount)
3. Routing files to appropriate directories (`/app/invoices/` vs `/app/other/`)
4. Generating a summary CSV with extracted amounts and totals

## Robust Approach

### Text Extraction Strategy

**PDFs (text-embedded):**
- Use `pdftotext <file> -` first — most reliable for small text-based PDFs
- Fallback to PyMuPDF (`fitz`) if pdftotext fails
- These PDFs are typically ~800 bytes with embedded text, not scanned images

**Images (JPG/PNG) with OCR:**
- **Critical:** Try raw pytesseract with multiple PSM modes (3, 6, 11) FIRST
- Only add light preprocessing (contrast 1.3) if ALL modes produce < 20 chars
- **Never use aggressive preprocessing** (contrast 2.0 + sharpen) — it destroys OCR on many images
- Collect text from all PSM modes for robust extraction

```python
# Correct approach for images
all_texts = []
for psm in [3, 6, 11]:
    text = pytesseract.image_to_string(img, config=f'--psm {psm}')
    all_texts.append(text)

# Only preprocess if needed
if all(len(t.strip()) < 20 for t in all_texts):
    img_gray = img.convert('L')
    img_enhanced = ImageEnhance.Contrast(img_gray).enhance(1.3)
    # ... retry with enhanced image
```

### Classification: Multi-Signal Scoring with Fuzzy Matching

Use a scoring system with fuzzy matching to handle OCR errors:

**Anti-signals (immediate "other"):**
- "this notice is not a tax invoice"
- "purchase order" (pre-invoice, not approved)
- "expense reimbursement" (internal HR doc)
- "receipt" (proof of payment, not a request for payment)
- "bank statement", "delivery note", "packing slip"

**Strong invoice signals (+3 points each):**
- "invoice", "tax invoice", "charge note", "billing statement"
- "tax document", "remittance notice"

**Moderate invoice signals (+2 points each):**
- "bill to", "ship to", "amount due", "total due"
- "grand total", "payable total", "total paid"

**Structural signals (+1-2 points each):**
- Has reference number (e.g., "Invoice No:", "Reference:")
- Has customer (e.g., "Bill To:", "Customer:")
- Has subtotal/subtotal-like field
- Has tax/VAT field
- Has total/total-like field

**Bonus (+3 points):** Document has full financial structure (reference + customer + tax + total)

**Threshold:** Score >= 5 → invoice, else → other

### Classification: Multi-Signal Scoring with Selective Fuzzy Matching

Use a scoring system with **selective** fuzzy matching:
- **Anti-signals:** Use exact string matching with explicit OCR variants (see below)
- **Positive signals:** Use fuzzy matching (max_distance=2) to handle OCR noise

**Why separate strategies?** Generic fuzzy matching on anti-signals causes false positives:
- "billing statement" could accidentally match "bank statement" with fuzzy matching
- "hardware order" could match "purchase order" with fuzzy matching
- Exact matching prevents legitimate invoice terms from triggering anti-signals

**Anti-signals (immediate "other") — use exact matching:**
- "this notice is not a tax invoice"
- "purchase order" (pre-invoice, not approved)
- "expense reimbursement" (internal HR doc)
- "receipt" (proof of payment, not a request for payment)
- "bank statement", "delivery note", "packing slip"

**OCR variants for critical anti-signals (add to exact match list):**
- receipt: "receict", "receipl", "recelpt"
- purchase order: "purchase ordr", "purchas order"

### Amount Extraction: Frequency Voting + Arithmetic Computation

**For clean PDFs (label-based extraction):**
```python
# Extract amounts after specific labels
total_labels = [r'(?:grand\s+total|amount\s+due|total\s+due|payable\s+total)']
vat_labels = [r'(?:vat|tax|gst|sales\s+tax)']
subtotal = extract_amount_after_label(text, r'subtotal|sub.?total')

# Cross-validate: vat = total - subtotal
```

**For noisy OCR images (frequency voting + compute):**

1. **Collect labeled numbers across all PSM modes:**
   - Categorize each number by line content (subtotal/vat/total/service)
   - Count frequency of each value

2. **Subtotal:** Pick most frequent value (usually stable with decimals)

3. **Total:** Find value that makes arithmetic sense
   - If number has no decimal and > 100, divide by 100 (OCR dropped decimal)
   - Sanity check: total > subtotal and total < 5x subtotal

4. **VAT:** Try multiple strategies in order:
   - Extract clean `X.XX` from VAT-labeled lines
   - Extract any `\d+\.\d{2}` from lines between service items and total
   - **Compute:** vat = total - subtotal (most reliable when OCR is noisy)

**Key insight:** OCR systematically drops decimal points (5420 should be 54.20) and misreads single digits. Arithmetic validation catches these errors.

### Handling Numeric Conventions

**Standard format:** `1,234.56` (comma = thousands, period = decimal)
**European format:** `1.234,56` (period = thousands, comma = decimal)

Detection heuristic: If last separator is comma with exactly 2 digits after, treat comma as decimal separator.

```python
def parse_amount(amount_str: str):
    cleaned = re.sub(r'[$€£¥\s]', '', amount_str)
    # European: 1.234,56
    if re.match(r'^[\d.]+,\d{2}$', cleaned):
        cleaned = cleaned.replace('.', '').replace(',', '.')
    else:
        # Standard: remove commas
        cleaned = cleaned.replace(',', '')
    return float(cleaned)
```

## Dependencies

- `pdftotext` (command-line tool, usually in `poppler-utils` package)
- `pytesseract` (Python wrapper for Tesseract OCR)
- `PIL` / `Pillow` (image processing)
- Standard library: `csv`, `shutil`, `subprocess`, `re`, `pathlib`, `collections.Counter`

## Critical Classification Distinction: Invoice vs Receipt

**Invoices** are requests for payment (issued BEFORE payment). They create a financial obligation.
**Receipts** are proof of payment (issued AFTER payment). They confirm a completed transaction.

A receipt may have subtotal + tax + total structure, but the presence of "Card Payment Approved", "Total Paid", or "Receipt" indicates the transaction is already settled. These belong in "other", not "invoice".

This is a **family invariant**: any document that is primarily a receipt (proof of payment) should be classified as "other" regardless of its financial structure.

## Edge Case Document Types (Family Variations)

The spec warns about "non-invoice documents that contain overlapping financial vocabulary." Watch for:

- **Pro Forma Invoice**: Preliminary invoice, not a binding payment request → "other"
- **Credit Note**: Reduces amount owed, related to invoicing but different document type → "other"
- **Debit Note**: Increases amount owed, similar to credit note → "other"
- **Quote/Estimate**: Price proposal before commitment → "other"
- **Statement of Account**: Summary of transactions, not a payment request → "other"

These may have full financial structure (subtotal + tax + total) but are not invoices. Add them to anti-signals if encountered in family variants.

## Known Failure Modes and Solutions

1. **Aggressive image preprocessing destroys OCR**
   - Contrast 2.0 + sharpen makes text unreadable
   - Try raw image first, only use light preprocessing (contrast 1.3) if needed

2. **OCR systematically drops decimal points**
   - "5420" interpreted as 5420.00 instead of 54.20
   - If number > 100 with no decimal in total/vat context, divide by 100

3. **OCR misreads single digits across PSM modes**
   - Same line gives "49.27", "48.27", "48.27" in different modes
   - Use frequency voting (most common value) + arithmetic validation

4. **Garbled tax lines with no clear label**
   - Can't extract VAT from "ast78.40" (OCR error for "Tax: 78.40")
   - Extract any `\d+\.\d{2}` from lines between service items and total
   - Fallback: compute VAT = total - subtotal

5. **Documents with overlapping financial vocabulary**
   - "Purchase Order" has amounts but isn't an invoice
   - "Receipt" has subtotal + tax + total but isn't an invoice
   - Use anti-signals and document type detection, not just amount presence

6. **Receipts misclassified as invoices**
   - Receipts have full financial structure (subtotal + tax + total)
   - But they represent completed transactions, not payment requests
   - Always check for "receipt", "total paid", "card payment approved" as anti-signals

7. **Fuzzy matching causes anti-signal false positives**
   - Generic fuzzy matching (max_distance=2) on anti-signals can match legitimate invoice terms
   - Example: "billing statement" ≈ "bank statement" with fuzzy matching
   - Solution: Use exact string matching for anti-signals, fuzzy matching only for positive signals
   - Maintain explicit OCR variant lists for critical anti-signals (receipt, purchase order)

## Adaptation for Family Variations

### document_content_patterns
- Adjust strong/moderate signal lists for domain-specific document types
- Add domain-specific anti-signals (e.g., "quote", "estimate" for non-invoices)
- Tune scoring threshold based on document diversity

### document_modality_and_ocr_noise
- For very noisy scans: increase PSM mode diversity, add more preprocessing attempts
- For mixed PDFs (some scanned, some text): detect text presence, use OCR only when needed
- For different languages: adjust Tesseract language config (`-l` flag)

### financial_field_expression
- Expand label patterns for different total/tax terminology
- Handle multiple pages/sections by extracting from all and selecting most plausible
- Support different currency symbols and formats

### batch_scale_and_class_balance
- Script already handles arbitrary batch sizes
- For very large batches: add progress reporting, consider parallel processing
- For invoice-heavy or other-heavy batches: no changes needed, scoring is per-document

## Example Usage

```bash
# Process documents in /app/documents/
python3 process_documents.py

# Output:
# - /app/invoices/ (invoice files + summary.csv)
# - /app/other/ (non-invoice files)
# - /app/documents/ (empty after processing)
```

## Verification Checklist

- [ ] All PDFs and images processed
- [ ] Documents correctly classified (spot-check a few)
- [ ] Extracted amounts make sense (total > subtotal, vat < total)
- [ ] summary.csv has correct columns and total row
- [ ] /app/documents/ is empty after processing
- [ ] All files preserved (moved, not deleted)
