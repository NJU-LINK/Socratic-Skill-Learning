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

**Challenge**: Documents use varied terminology and may have overlapping financial vocabulary. A receipt, payment reminder, purchase order, and invoice all contain monetary amounts but serve different purposes. OCR noise can garble key terms (e.g., "receipt" → "receict", "total paid" → "otal paid"). The spec explicitly mentions "invoices with weaker or less standard invoice markers" and "non-invoice documents that contain overlapping financial vocabulary".

**Solution**: Use semantic reasoning with weighted scoring:
- **Understand document purpose**: Invoice requests payment (future obligation), receipt confirms payment (past transaction), purchase order requests goods (not billing), payment reminder references existing invoice
- **Check signals against combined text**: Merge all OCR candidates before classification to catch signals that may appear in only one candidate
- **Weighted scoring for both classes**: Assign weights to signals (strong=5, medium=3-4, weak=2) and sum scores
- **OCR-aware patterns**: Include common OCR misrecognitions for key terms (e.g., `recei[cp]t` for "receipt", `inv[ao]ice` for "invoice", `paym?ent` for "payment")
- **Conflict resolution**: When both scores are high, use additional heuristics (payment terms, due dates, customer/vendor relationships)
- **Intentional default**: Default to `other` when neither class has strong signals (safer to miss an invoice than include a non-invoice in financial summary)

**Key insight**: Never rely on silent defaults. Actively confirm both classes. The document's **purpose** matters more than the presence of financial data or specific keywords. Look for semantic indicators: payment terms ("due within 14 days", "net 30") suggest invoice; payment confirmation ("paid", "received", "approved") suggests receipt or non-invoice.

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

**For scanned PDFs** (PDFs with no embedded text, essentially images): If `page.get_text()` returns empty or very short text, the PDF page is likely a scanned image. In this case:
1. Use fitz to render the page as an image: `pix = page.get_pixmap(dpi=300)`
2. Convert to PIL Image and run OCR with pytesseract
3. Fall back to the same multi-candidate OCR strategy used for JPG/PNG files

```python
def extract_text_pdf(path):
    doc = fitz.open(path)
    all_text = []
    for page in doc:
        text = page.get_text()
        # If text is very short, page is likely a scanned image
        if len(text.strip()) < 50:
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            # Use multi-candidate OCR
            for psm in [3, 4, 6]:
                try:
                    ocr_text = pytesseract.image_to_string(img, config=f'--psm {psm}')
                    all_text.append(ocr_text)
                except:
                    pass
        else:
            all_text.append(text)
    doc.close()
    return all_text  # Return list of candidates, not single string
```

**For Images**: Use pytesseract with multiple PSM modes:
```python
for psm in [3, 4, 6]:
    text = pytesseract.image_to_string(img, config=f'--psm {psm}')
```

### Classification Logic

```python
def classify_document(texts):
    """
    Classify document using semantic reasoning and weighted scoring.
    
    Key principle: Understand document PURPOSE, not just keywords.
    - Invoice: requests payment for goods/services (future obligation)
    - Receipt: confirms payment was made (past transaction)
    - Purchase order: requests goods/services (not a billing document)
    - Payment reminder: references existing invoice (not a new invoice)
    """
    combined = ' '.join(texts).lower()
    
    # Check for negation patterns first (e.g., "not a tax invoice", "not an invoice")
    # These should suppress invoice signals
    has_negation = bool(re.search(r'\bnot (a|an) .*\binvoice\b', combined))
    
    # Score non-invoice signals (check against combined text)
    # Include OCR-aware patterns and broader document types
    non_invoice_score = 0
    non_invoice_patterns = [
        # Receipts and payment confirmations
        (r'\breceipt\b', 5), (r'\brecei[cp]t\b', 4),  # OCR variants
        (r'\btotal paid\b', 4), (r'\bpaid in full\b', 4),
        (r'\bcard payment\b', 3), (r'\bpayment (approved|received|confirmed)\b', 4),
        (r'\bpaid\b', 1),  # Weak signal alone; too broad if weight=2 (e.g., "Amount Paid" on invoice copy)
        
        # Explicit non-invoice documents
        (r'\bnot a (tax )?invoice\b', 5),
        (r'\bpurchase order\b', 5), (r'\bp\.?o\.?\s*(number|no|#|\d)', 3),  # PO with context, not just "P.O. Box"
        (r'\bexpense reimbursement\b', 5),
        (r'\bpayment reminder\b', 5), (r'\bpast due notice\b', 4),
        (r'\bapproval status:\s*pending\b', 4),
        (r'\bquote\b', 4), (r'\b(cost|price|budget)\s+estimate\b', 3),  # "estimate" alone is too broad (matches "Estimated Tax")
        (r'\bproposal\b', 3),
        (r'\bdelivery note\b', 4), (r'\bpacking slip\b', 4),
        (r'\bcredit note\b', 4), (r'\bdebit note\b', 4),
        
        # Semantic indicators of non-invoice
        (r'\bthank you for your payment\b', 4),
        (r'\bpayment has been (received|processed|approved)\b', 4),
    ]
    for pattern, weight in non_invoice_patterns:
        if re.search(pattern, combined):
            non_invoice_score += weight
    
    # Score invoice signals
    # If negation detected (e.g., "not a tax invoice"), skip invoice scoring
    invoice_score = 0
    if not has_negation:
        invoice_patterns = [
            # Direct invoice terminology
            (r'\binvoice\b', 5), (r'\binv[ao]ice\b', 4),  # OCR variants
            (r'\btax invoice\b', 5), (r'\bcommercial invoice\b', 5),
            (r'\bbilling statement\b', 4), (r'\bstatement of account\b', 4),
            (r'\bcharge note\b', 4), (r'\bcharge\b.*\bnote\b', 3),
            (r'\bremittance (notice|advice)\b', 4),
            
            # Payment request language
            (r'\bplease remit\b', 4), (r'\bremit (payment|amount)\b', 3),
            (r'\bamount due\b', 3), (r'\bbalance due\b', 3),
            (r'\bpayable total\b', 3), (r'\btotal due\b', 3),
            (r'\bgrand total\b', 3), (r'\bnet total\b', 3),
            (r'\bbill to\b', 3), (r'\bship to\b.*\b(invoice|bill)\b', 3),
            
            # Payment terms (suggest invoice)
            (r'\b(net \d+|due within \d+ days|due on|payment terms)\b', 3),
            (r'\bplease pay (within|by)\b', 3),
        ]
        for pattern, weight in invoice_patterns:
            if re.search(pattern, combined):
                invoice_score += weight
    
    # Conflict resolution: when both scores are high, use additional heuristics
    if non_invoice_score >= 3 and invoice_score >= 3:
        # Check for semantic indicators
        if re.search(r'\b(payment (terms|due)|remit|bill to|ship to)\b', combined):
            # Payment request language suggests invoice
            invoice_score += 2
        if re.search(r'\b(thank you for|payment (received|processed|approved)|paid in full)\b', combined):
            # Payment confirmation suggests non-invoice
            non_invoice_score += 2
    
    # Decide with explicit thresholds
    if non_invoice_score >= 3:
        return 'other'
    if invoice_score >= 3:
        return 'invoice'
    
    # Intentional default: safer to miss an invoice than include non-invoice
    return 'other'
```

**Key design decisions**:
- **Semantic reasoning**: Understand document purpose, not just keyword matching
- **Negation handling**: Check for "not a/an ... invoice" patterns first and suppress invoice scoring entirely when detected. This prevents "This notice is not a tax invoice" from generating false invoice signals.
- **Broader coverage**: Handle credit notes, debit notes, quotes, estimates, proposals, delivery notes, packing slips
- **OCR-aware patterns**: Cover common misrecognitions for key terms (`recei[cp]t`, `inv[ao]ice`, `paym?ent`)
- **Conflict resolution**: When both scores are high, use additional semantic heuristics
- **Non-invoice signals checked against combined text**: Catches signals in any OCR candidate
- **Weighted scoring**: Prevents one noisy match from dominating
- **Threshold of 3**: Requires at least one medium signal or partial strong signal
- **Default to `other`**: Intentional and documented as safer choice

### Financial Field Extraction

**Total amount patterns** (in priority order):
- `grand total`, `payable total`, `amount due`, `total due`, `balance due`, `net total`
- Fallback: `total` (with word boundary to avoid matching "subtotal")

**VAT/Tax patterns**:
- `VAT`, `sales tax`, `GST` followed by amount
- `tax`, `vat` followed by amount
- `vat included`, `vat amount` followed by amount

**VAT/Tax extraction — CRITICAL PITFALL**:
When a tax label is followed by a rate percentage, the percentage appears BEFORE the monetary amount. "VAT 10%: 128.00" means the VAT amount is 128.00, NOT 10. Your regex MUST explicitly skip the optional percentage:

```python
# RIGHT: explicitly consumes the optional percentage before capturing
r'(?:VAT|sales\s+tax|GST)[:\s]*(?:\d+%)?[:\s]*[€$£]?\s*([\d,]+\.?\d*)'
                                        ^^^^^^^^
                                   This group is essential.

# WRONG: captures "10" from "VAT 10%: 128.00" instead of "128.00"
r'(?:VAT|sales\s+tax|GST)[^\d]*?([\d,]+\.?\d*)'
```

Without `(?:\d+%)?`, the non-greedy `[^\d]*?` stops at the first digit (the "1" in "10%"), capturing the percentage instead of the monetary amount. This is a common mistake that produces incorrect VAT amounts.

**Computation strategies**:
1. If total and subtotal found: `vat = total - subtotal`
2. If VAT rate and subtotal found: `vat = subtotal × rate / 100`
3. Cross-validate across OCR candidates: find amount X where `total - X` appears in another candidate

**Multiple total candidates**: When an invoice has multiple amounts labeled "total" (e.g., "Subtotal", "Total before discount", "Amount Due"), use priority-based selection:

```python
# Priority order for total amount labels
TOTAL_LABEL_PRIORITY = [
    r'amount\s+due', r'total\s+due', r'balance\s+due',
    r'payable\s+total', r'grand\s+total', r'net\s+total', r'total'
]

def select_total(candidates):
    """
    candidates: list of (label, amount) tuples
    Returns the amount with highest priority label, or largest amount if tied.
    """
    for pattern in TOTAL_LABEL_PRIORITY:
        matches = [(label, amt) for label, amt in candidates 
                   if re.search(pattern, label, re.IGNORECASE)]
        if matches:
            # If multiple matches with same priority, pick largest amount
            return max(amt for _, amt in matches)
    # Fallback: no labeled totals found, pick largest amount overall
    return max(amt for _, amt in candidates) if candidates else None
```

**Different numeric conventions**: The `parse_amount` function handles standard format (1,234.56), European format (1.234,56), and currency symbols. For European format detection, use pattern `\d+\.\d{3},\d{2}` to distinguish from standard format.

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
