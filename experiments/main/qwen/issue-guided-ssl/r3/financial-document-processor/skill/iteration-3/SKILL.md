---
name: financial-document-processor
description: Classify mixed PDF/JPG financial documents as invoice or other, extract monetary amounts with OCR noise tolerance, route files to appropriate directories, and generate summary CSV with totals.
---

# Financial Document Processor

Process mixed batches of PDF and JPG financial documents by classifying them as invoices or non-invoices, extracting monetary amounts, routing files to appropriate directories, and generating a summary CSV.

## Core Capabilities

1. **Multi-signal document classification** using pro-invoice and anti-invoice pattern scoring
2. **OCR-tolerant amount extraction** with mathematical consistency validation
3. **Automated file routing** to separate invoice and non-invoice directories
4. **Summary CSV generation** with per-invoice amounts and aggregate totals

## Processing Pipeline

### 1. Text Extraction

**PDF files:** Use `pdftotext` command-line tool for reliable text extraction from embedded text layers.

**JPG/image files:** Use `pytesseract` OCR with multiple PSM (Page Segmentation Mode) settings (3, 4, 6, 11).

**Critical architectural distinction:**
- **Classification** uses COMBINED text from all PSM modes (more signals = better classification accuracy)
- **Amount extraction** uses PER-PSM independent extraction with mathematical consistency scoring

**Why per-PSM extraction for amounts?** Different PSM modes often produce contradictory readings of the same field. For example:
- PSM 6 might read "Freight Services 880.00"
- PSM 4 might read "Freight Services 980.00"

If we combine these texts and use regex with last-match-wins, the result is arbitrary. Instead, we extract amounts from each PSM mode independently, then select the result with the best mathematical consistency (subtotal + VAT ≈ total). This ensures the result is determined by physics (the math), not by regex ordering.

OCR output is often noisy with:
- Missing decimal points (e.g., "483" instead of "4.83")
- Character substitutions (e.g., "ast" instead of "gst", "receict" instead of "receipt")
- Inconsistent readings across different PSM modes

### 2. Multi-Signal Classification

**Do not rely on the word "invoice" alone** — many invoices use alternative labels (Tax Document, Billing Statement, Remittance Notice, Charge Note) and non-invoices may contain financial vocabulary.

**Critical distinction: Receipts are NOT invoices.** Payment receipts (showing "card payment approved", "VAT included", "total paid") are payment confirmations, not formal billing documents. Charge notes, however, ARE invoices.

**Pro-invoice signals** (each adds +1 to score):
- Document type headers: invoice, tax invoice, tax document, billing statement, bill, remittance notice, charge note, charge invoice, sales invoice
- Final-amount labels: grand total, amount due, total due, payable total, balance due, total payable, total amount
- Tax indicators: VAT, GST, sales tax
- Transaction context: customer, client, vendor, bill to, ship to

**NOT pro-invoice signals** (these are receipt/payment signals, not invoice signals):
- receipt, payment receipt, payment approved, card payment, total paid, subtotal

**Anti-invoice signals** (each adds -2 to score, often decisive):
- Explicit disclaimers: "not a tax invoice", "this notice is not..."
- Pre-transaction documents: purchase order, quote, estimate, pro forma, proposal
- Non-finality indicators: approval status pending, draft, requested, estimated
- Reminder/collection documents: payment reminder, dunning letter, statement of account, outstanding balance
- Internal documents: expense reimbursement, reimbursement summary, reclaimable
- Receipt/payment confirmation signals: receipt, payment approved, card payment

**Classification logic:**
1. Check for explicit disclaimers first (immediate rejection)
2. Count pro-invoice signals using OCR-tolerant fuzzy matching
3. Count anti-invoice signals (exact match, weighted double)
4. Classify as invoice if: pro_score ≥ 3 AND pro_score > anti_weighted
5. Default to non-invoice if ambiguous (safer choice)

**OCR-tolerant matching:** Uses character-by-character replacement with OCR-confusable character classes (p↔b, c↔e, i↔l↔1, o↔0↔a, s↔z, n↔r, t↔l, v↔u, f↔t, g↔q↔a) to handle common OCR errors like "Charge Nate" → "Charge Note", "ast" → "gst", "Teal Due" → "Total Due".

### 3. Amount Extraction

Extract two key amounts from invoices:
- **total_amount**: Final amount including tax (look for: grand total, amount due, total due, payable total, balance due, total paid)
- **vat_amount**: Tax/VAT/GST amount (look for: VAT, GST, sales tax, tax)

**Extraction strategy depends on document type:**

**For PDFs (clean text):**
1. Use regex patterns to find labeled amounts (e.g., `Total Due: 1,408.00`)
2. Parse amounts handling commas, currency symbols, and European formats
3. Apply mathematical consistency checks: total_amount ≈ subtotal_amount + vat_amount
4. Handle special VAT formats:
   - "VAT 10%: 128.00" → percentage notation must be consumed before capturing amount
   - "Subtotal: 1000.00, VAT 20%" → extract tax rate and compute VAT = subtotal × rate
   - Only apply /100 correction for OCR noise when amount has NO decimal point (e.g., "483" → "4.83")
   - If amount already has decimal places (e.g., "128.00"), it's likely correct — do NOT divide by 100
   - Use the largest amount as total if labeled total is missing
   - Compute missing values from mathematical relationships when possible:
     * vat = total - subtotal (when both available)
     * total = subtotal + vat (when both available)
     * vat = subtotal × rate (when rate and subtotal available, no explicit VAT amount)

**For OCR documents (JPG/PNG):**
1. Extract amounts from EACH PSM mode independently (not combined text)
2. For each PSM result, score by mathematical consistency:
   - Score 3: Perfect consistency (subtotal + VAT ≈ total within ±0.10)
   - Score 1: Partial (have all three values but inconsistent)
   - Score 0: Only total found
3. Select the PSM result with highest consistency score
4. This avoids the problem where different PSM modes produce contradictory readings of the same field

**Why per-PSM extraction?** Different PSM modes often read the same field differently (e.g., PSM 6 reads "880.00", PSM 4 reads "980.00"). If we combine texts and use last-match-wins, the result is arbitrary. Per-PSM extraction with mathematical consistency scoring ensures the result is determined by physics (the math), not by regex ordering.

**Amount parsing:**
- Remove currency symbols and whitespace
- Handle thousands separators (commas) vs decimal separators
- European format: 1.234,56 → 1234.56
- Standard format: 1,234.56 → 1234.56
- If both comma and period exist, the last one is the decimal separator

### 4. File Routing and Summary Generation

1. Create `/app/invoices/` and `/app/other/` directories
2. Move each document to appropriate directory based on classification
3. Generate `/app/invoices/summary.csv` with columns: filename, total_amount, vat_amount
4. Add one row per invoice with amounts formatted to 2 decimal places
5. Add final row with filename="total" and summed amounts
6. Verify `/app/documents/` is empty after processing

## Handling Variations

### Document Content Patterns (Axis 1)

**Invoices with weak/non-standard markers:**
- Use multiple pro-invoice signals rather than relying on a single keyword
- Look for transaction context (customer, vendor, bill to) combined with monetary amounts
- Charge notes should be classified as invoices; simple payment receipts are NOT invoices

**Non-invoices with overlapping financial vocabulary:**
- Anti-invoice signals are weighted more heavily (×2) because they're usually decisive
- Explicit disclaimers ("not an invoice") override all other signals
- Pre-transaction documents (POs, quotes) are not invoices even if they contain amounts

**Classification cues spread across text regions:**
- Combine signals from entire document text, not just headers
- OCR from multiple PSM modes captures more signals from different regions

### Document Modality and OCR Noise (Axis 2)

**Noisy OCR output:**
- Use multiple PSM modes for robustness
- For CLASSIFICATION: combine text from all PSM modes (more signals = better)
- For AMOUNT EXTRACTION: extract per-PSM independently, select most mathematically consistent result
- Apply fuzzy pattern matching with OCR-confusable character substitutions
- Use mathematical consistency (subtotal + VAT ≈ total) to validate and correct extracted amounts
- Handle missing decimal points by checking if dividing by 100 gives reasonable values
- Avoid last-match-wins arbitrariness by using per-PSM scoring

**Mixed embedded text and rendered pages:**
- `pdftotext` handles embedded text; for rendered pages, convert to image and use OCR
- Combine both approaches for PDFs with mixed content

**Partially legible fields:**
- Extract what's available and infer missing values from mathematical relationships
- Use the largest amount as total if labeled total is unclear
- Cross-validate subtotal + VAT = total to catch OCR errors

### Financial Field Expression (Axis 3)

**Different numeric conventions:**
- Handle both standard (1,234.56) and European (1.234,56) formats
- Parse amounts with and without thousands separators
- Detect and correct missing decimal points from OCR errors

**Taxes recovered from subtotals or rates:**
- If VAT amount is missing but subtotal and total are known: vat = total - subtotal
- If total is missing but subtotal and VAT are known: total = subtotal + vat
- If VAT amount is missing but tax rate and subtotal are available: vat = subtotal × rate / 100
  * Extract tax rate from patterns like "VAT 20%", "GST 10%", "Tax 15%"
  * Validate computed VAT against total if available (total ≈ subtotal + computed_vat)
  * Common rates: 5%, 8%, 10%, 12%, 15%, 20%, 25%
- If only rate is shown (no explicit VAT amount), compute from subtotal and rate

**Multiple amount candidates:**
- Prefer labeled amounts over unlabeled ones
- For totals, prefer the last occurrence (usually the final summary)
- For VAT, prefer the first occurrence (usually the main tax line)
- Use mathematical consistency to select the correct candidate

### Batch Scale and Class Balance (Axis 4)

**Small or large batches:**
- Process all PDF and JPG files in the documents directory
- Maintain consistent ordering (alphabetical by filename)
- Summary CSV scales correctly regardless of batch size

**Invoice-heavy or other-heavy mixes:**
- Classification logic works independently for each document
- Summary CSV only includes invoices, so class balance doesn't affect output format
- Total row always sums the invoice rows correctly

## Implementation Notes

**Required tools:**
- `pdftotext` (poppler-utils) for PDF text extraction
- `tesseract` + `pytesseract` + `PIL` for OCR
- Python 3 with standard library (os, re, csv, shutil, subprocess)

**Error handling:**
- If text extraction fails, classify document as "other" (safer default)
- If amount extraction fails, use 0.00 as placeholder
- Log warnings for missing or inconsistent values

**Performance:**
- Process documents sequentially to avoid memory issues with large images
- Multiple OCR passes (4 PSM modes) increase accuracy but take more time
- For very large batches, consider parallelizing OCR across documents

## Example Usage

```python
# Run the processing script
python3 process_documents.py

# Expected output structure:
# /app/documents/     (empty after processing)
# /app/invoices/
#   ├── invoice1.pdf
#   ├── invoice2.jpg
#   └── summary.csv
# /app/other/
#   ├── document1.pdf
#   └── document2.jpg
```

**summary.csv format:**
```csv
filename,total_amount,vat_amount
invoice1.pdf,751.68,55.68
invoice2.jpg,1058.40,78.40
total,1810.08,134.08
```

## Testing and Validation

**Verify classification accuracy:**
- Check that explicit disclaimers ("not an invoice") result in "other" classification
- Verify that charge notes are classified as "invoice"
- Verify that simple payment receipts are classified as "other" (NOT invoices)
- Ensure purchase orders, payment reminders, and expense reimbursements are classified as "other"

**Verify amount extraction:**
- Check mathematical consistency: total ≈ subtotal + VAT (within ±0.10)
- Verify amounts are formatted to 2 decimal places in CSV
- Ensure total row sums match the sum of invoice rows

**Verify file routing:**
- Confirm `/app/documents/` is empty after processing
- Check that all files are preserved (not deleted) in appropriate directories
- Verify summary.csv exists and has correct format

## Common Pitfalls

1. **Relying on "invoice" keyword alone** — many invoices don't contain this word
2. **Classifying based on monetary amounts alone** — non-invoices have amounts too
3. **Treating receipts as invoices** — payment receipts (card payment approved, VAT included, total paid) are NOT invoices; charge notes ARE invoices
4. **Ignoring OCR noise** — missing decimal points and character substitutions are common (e.g., "Charge Nate" → "Charge Note", "ast" → "gst")
5. **Not using mathematical consistency** — total = subtotal + VAT is a powerful validation
6. **Forgetting the summary total row** — tests expect a final "total" row with sums
7. **Not handling European number formats** — commas and periods have different meanings
8. **Moving files without preserving them** — use `shutil.move` to preserve file integrity
9. **Combining PSM texts for amount extraction** — different PSM modes produce contradictory readings of the same field; use per-PSM extraction with mathematical consistency scoring instead
10. **Last-match-wins arbitrariness** — when multiple PSM modes read the same field differently, the "last" match is arbitrary; use consistency scoring to select the correct reading
11. **Incorrectly dividing VAT by 100** — only apply /100 correction for OCR noise when amount has NO decimal point; if amount already has decimal places (e.g., "128.00"), it's likely correct
12. **Using permissive classification thresholds** — require pro_score ≥ 3 minimum; the pro_score ≥ 2 fallback allows receipts to be misclassified as invoices
13. **Not handling "VAT 10%: 128.00" format** — percentage notation must be consumed before capturing the actual amount
14. **Not extracting tax rates when VAT amount is missing** — if invoice shows "Subtotal: 1000.00, VAT 20%" without explicit VAT amount, extract rate and compute VAT = subtotal × rate / 100
