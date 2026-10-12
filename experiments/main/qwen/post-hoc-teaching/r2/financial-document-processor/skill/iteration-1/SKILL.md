---
name: financial-document-processor
description: Process mixed batches of business documents by classifying invoices from non-invoices, extracting financial totals and tax amounts, organizing files into appropriate directories, and generating summary reports.
---

# Financial Document Processor

## Overview

This skill processes batches of mixed business documents (PDFs and images) to:
1. Classify each document as `invoice` or `other` based on content analysis
2. Extract financial data (total amount and VAT/tax amount) from invoices
3. Organize documents into separate directories
4. Generate a CSV summary with invoice details and totals

## Key Challenges & Solutions

### 1. Document Classification

**Challenge**: Documents use varied terminology and may have overlapping financial vocabulary. A receipt, payment reminder, purchase order, and invoice all contain monetary amounts but serve different purposes. OCR noise can garble key terms (e.g., "receipt" → "receict", "total paid" → "otal paid").

**Solution**: Use weighted scoring with multi-candidate merging:
- **Check signals against combined text**: Merge all OCR candidates before classification to catch signals that may appear in only one candidate
- **Weighted scoring for both classes**: Assign weights to signals (strong=5, medium=3-4, weak=2) and sum scores
- **OCR-aware patterns**: Include common OCR misrecognitions (e.g., `recei[cp]t` for "receipt")
- **Intentional default**: Default to `other` when neither class has strong signals (safer to miss an invoice than include a non-invoice in financial summary)

**Key insight**: Never rely on silent defaults. Actively confirm both classes. The document's purpose matters more than the presence of financial data. A receipt confirms payment (past tense), while an invoice requests payment (future tense).

### 2. OCR Noise Handling

**Challenge**: Image-based documents (JPG, PNG) require OCR, which produces noisy text with misread characters, missing decimal points, and garbled labels (e.g., "ast" instead of "Tax", "880.00" instead of "980.00").

**Solution**: Multi-candidate OCR strategy:
- Extract text using multiple Tesseract PSM modes (3, 4, 6)
- Each mode may produce different errors but also different correct readings
- Merge information across candidates rather than picking a single "best" text
- Use cross-validation: if total appears in one candidate and subtotal in another, compute tax = total - subtotal

**Key insight**: Different OCR modes optimize for different layouts. PSM 6 (uniform block) often gives better numeric accuracy, while PSM 3/4 (fully automatic) may capture more text structure. Combining both yields the most reliable results.

### 3. Financial Field Extraction

**Challenge**: Totals and taxes are expressed in varied ways: "Grand Total", "Amount Due", "Payable Total", "Total Due", "VAT", "Tax", "Sales Tax", "VAT 10%", etc. Some documents require computation (total - subtotal = tax). Cross-validation can be polluted by non-monetary numbers (dates, document IDs, OCR artifacts).

**Solution**: Multi-strategy extraction with context-aware filtering:
1. **Direct extraction**: Use regex patterns for common labels, ordered by specificity (e.g., "grand total" before "total")
2. **Computation from components**: If total and subtotal are found, compute tax = total - subtotal
3. **Rate-based computation**: If tax rate percentage is found with subtotal, compute tax = subtotal × rate
4. **Context-filtered cross-validation**: When multiple OCR candidates provide different amounts, verify consistency but filter candidates to only those near financial keywords or within plausible monetary range (within 10x of detected total)

**Key insight**: Word boundaries matter. "Total" should not match inside "Subtotal". Use `(?<!\w)total` or explicit label lists to avoid false matches. Cross-validation should exclude dates, document IDs, and OCR artifacts that could pollute the computation.

### 4. Amount Parsing

**Challenge**: Monetary amounts appear in various formats: "1,408.00" (with comma), "751.68" (plain), "€100.00" (with currency symbol), European format "1.234,56".

**Solution**: Robust parsing function:
- Remove currency symbols and spaces
- Remove commas (standard thousands separator)
- Handle European format detection (pattern: digits.digits.digits)
- Convert to float with error handling

## Implementation Approach

### Text Extraction

**For PDFs**: Use PyMuPDF (fitz) to extract embedded text directly.

**For Images**: Use pytesseract with multiple PSM modes:
```python
for psm in [3, 4, 6]:
    text = pytesseract.image_to_string(img, config=f'--psm {psm}')
```

### Classification Logic

```python
def classify_document(texts):
    combined = ' '.join(texts).lower()
    
    # Score non-invoice signals (check against combined text)
    non_invoice_score = 0
    non_invoice_patterns = [
        (r'\breceipt\b', 5), (r'\brecei[cp]t\b', 4),  # OCR variant
        (r'\btotal paid\b', 4), (r'\bcard payment\b', 3),
        (r'\bpaid\b', 2), (r'\bnot a tax invoice\b', 5),
        (r'\bpurchase order\b', 5), (r'\bexpense reimbursement\b', 5),
        (r'\bpayment reminder\b', 5), (r'\bapproval status:\s*pending\b', 4),
    ]
    for pattern, weight in non_invoice_patterns:
        if re.search(pattern, combined):
            non_invoice_score += weight
    
    # Score invoice signals
    invoice_score = 0
    invoice_patterns = [
        (r'\binvoice\b', 5), (r'\bbilling statement\b', 4),
        (r'\bbill to\b', 3), (r'\bcharge note\b', 4),
        (r'\bremittance notice\b', 4), (r'\bplease remit\b', 4),
        (r'\bamount due\b', 3), (r'\bpayable total\b', 3),
        (r'\btotal due\b', 3), (r'\bgrand total\b', 3),
    ]
    for pattern, weight in invoice_patterns:
        if re.search(pattern, combined):
            invoice_score += weight
    
    # Decide with explicit thresholds
    if non_invoice_score >= 3:
        return 'other'
    if invoice_score >= 3:
        return 'invoice'
    
    # Intentional default: safer to miss an invoice than include non-invoice
    return 'other'
```

**Key design decisions**:
- Non-invoice signals checked against combined text (catches signals in any OCR candidate)
- OCR-aware patterns handle common misrecognitions
- Weighted scoring prevents one noisy match from dominating
- Threshold of 3 requires at least one medium signal or partial strong signal
- Default to `other` is intentional and documented

### Financial Field Extraction

**Total amount patterns** (in priority order):
- `grand total`, `payable total`, `amount due`, `total due`, `balance due`, `net total`
- Fallback: `total` (with word boundary to avoid matching "subtotal")

**VAT/Tax patterns**:
- `VAT`, `sales tax`, `GST` followed by amount
- `tax`, `vat` followed by amount
- `vat included`, `vat amount` followed by amount

**Computation strategies**:
1. If total and subtotal found: `vat = total - subtotal`
2. If VAT rate and subtotal found: `vat = subtotal × rate / 100`
3. Cross-validate across OCR candidates: find amount X where `total - X` appears in another candidate

### Multi-Candidate Merging

```python
# Collect amounts from all OCR candidates, filtered by context
def extract_contextual_amounts(text, total_amount):
    """Extract amounts that are likely monetary values, not dates/IDs."""
    amounts = set()
    lines = text.split('\n')
    
    for line in lines:
        # Skip lines that look like dates, IDs, or reference numbers
        if re.search(r'\b(date|ref|id|number|no)[:\s]*\d', line, re.IGNORECASE):
            continue
        
        # Extract amounts from this line
        for match in re.finditer(r'[\d,]+\.?\d*', line):
            parsed = parse_amount(match.group())
            if parsed and parsed > 0:
                # Filter: must be within plausible range (0.01 to 10x total)
                if total_amount and parsed > total_amount * 10:
                    continue
                amounts.add(parsed)
    
    return amounts

# Cross-validate with filtered amounts
all_amounts = set()
for text in ocr_candidates:
    all_amounts.update(extract_contextual_amounts(text, total_amount))

# Find amount X where (total - X) also exists in filtered set
for amt in sorted(all_amounts, reverse=True):
    if 0 < amt < total:
        diff = total - amt
        if diff in all_amounts:
            vat_amount = diff
            break
```

**Key design decisions**:
- Filter out lines containing date/ID/reference keywords
- Constrain amounts to plausible monetary range (within 10x of detected total)
- This prevents dates (2026, 2028), document IDs (10044), and OCR artifacts (7840 from "Tax 78.40") from polluting cross-validation

## File Organization

1. Create output directories: `/app/invoices/` and `/app/other/`
2. Move each document to appropriate directory based on classification
3. Generate `/app/invoices/summary.csv` with columns: `filename`, `total_amount`, `vat_amount`
4. Add final row with `filename=total` and summed numeric columns
5. Verify `/app/documents/` is empty after processing

## Edge Cases & Robustness

- **Noisy OCR**: Use multiple PSM modes and cross-validate
- **Missing fields**: Compute from available data (total - subtotal = tax)
- **Ambiguous classification**: Check multiple signal types, prioritize explicit markers
- **Various number formats**: Handle commas, currency symbols, European formats
- **Empty batches**: Handle gracefully, produce empty summary with just header and total row
- **Non-standard document types**: Fall back to "other" if classification is uncertain

## Dependencies

- **PyMuPDF (fitz)**: PDF text extraction
- **pytesseract**: OCR for image-based documents
- **PIL (Pillow)**: Image loading and preprocessing
- **Python standard library**: `re`, `csv`, `os`, `shutil` for file operations and text processing

## Verification Checklist

- [ ] All PDF and JPG files processed
- [ ] Documents correctly classified (invoice vs other)
- [ ] Invoices moved to `/app/invoices/`
- [ ] Non-invoices moved to `/app/other/`
- [ ] `/app/documents/` is empty
- [ ] `summary.csv` created with correct columns
- [ ] Each invoice has correct `total_amount` and `vat_amount`
- [ ] Final row has correct sums
- [ ] All file moves preserve original files (no data loss)
