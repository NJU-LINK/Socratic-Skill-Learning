---
name: financial-document-processor
description: >
  Classify mixed batches of financial/business documents as invoice or other,
  route them to appropriate output folders, extract total_amount and vat_amount
  from invoices, and produce a summary CSV with per-invoice rows plus a totals row.
  Robust to OCR noise, varied document titles, and diverse financial field expressions
  by using mathematical structure detection (golden triplets) with context-aware filtering.
---

# Financial Document Processor

## Overview

Process a batch of mixed financial/business documents (PDFs and images) by:
1. Classifying each document as `invoice` or `other`
2. Moving invoices to `/app/invoices/` and non-invoices to `/app/other/`
3. Extracting `total_amount` and `vat_amount` from each invoice
4. Writing `/app/invoices/summary.csv` with per-invoice rows plus a totals row

## Core Architecture: Golden Triplet Detection with Context-Aware Filtering

The fundamental insight is that **invoices have a mathematical invariant**: `subtotal + tax = total`. This structural property is far more robust than keyword matching because:
- Numbers survive OCR better than words
- The mathematical relationship holds regardless of document title or layout
- It works across languages, currencies, and formatting conventions

**Critical enhancement**: Extract amounts with their surrounding text context to filter out noise numbers (dates, reference IDs, PO numbers) that could create spurious triplets.

### Algorithm

```
1. Extract text from document (PDF: pdftotext; Images: tesseract with MULTIPLE PSM modes)
2. Normalize text: strip commas, lowercase
3. Filter out date lines entirely (they contain noise numbers like 2026.02)
4. Extract amounts WITH CONTEXT: for each line, identify monetary keywords, then extract numbers
5. Filter amounts: keep numbers that have monetary context OR have decimal points
6. Find "golden triplets": (a, b, c) where a + b ≈ c (within tolerance 0.02)
7. Check for explicit disclaimers that disqualify as invoice
8. Classification:
   - If disclaimer present → OTHER (overrides everything)
   - If golden triplet exists → INVOICE
   - Fallback: strong invoice keywords + total field → INVOICE
   - Otherwise → OTHER
9. For invoices, extract financial data:
   - Score each triplet using context-based label proximity
   - vat_amount = smaller addend from best triplet
   - total_amount = sum from best triplet
   - Cross-validate with mathematical consistency
```

## Implementation Details

### Text Extraction

**PDFs**: Use `pdftotext` command-line tool.

**Images**: Use `tesseract` with **MULTIPLE PSM (Page Segmentation Mode) values**. This is **CRITICAL** for robustness — different PSM modes capture different text:

```python
def extract_text_image(filepath):
    texts = []
    # Use multiple PSM modes to maximize OCR coverage
    for psm in [6, 3, 4, 11, 12]:
        result = subprocess.run(
            ["tesseract", str(filepath), "stdout", "--psm", str(psm)],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            texts.append(result.stdout)
    return "\n".join(texts)
```

**Why multiple PSM modes matter**:
- PSM 6: Assume a single uniform block of text (good for clean receipts)
- PSM 3: Fully automatic (good for mixed layouts)
- PSM 4: Assume a single column of text of variable sizes
- PSM 11: Sparse text, no particular order (good for scattered text)
- PSM 12: Sparse text with OSD

**In iteration 1, the fresh solver only used PSM 6 and still passed v01. But this is fragile — noisier OCR in other variants could fail with a single PSM mode. Always use multiple modes.**

### Text Normalization

Before amount extraction and pattern matching:
1. Strip all commas: `text.replace(',', '')`
2. Lowercase: `text.lower()`

This ensures "1,280.00" becomes "1280.00" and matches consistently.

**European number format handling**: Some documents may use "1.280,00" instead of "1,280.00". Detect this by checking if the text contains patterns like `\d+\.\d{3},\d{2}` and swap the separators before normalization.

### Context-Aware Amount Extraction

**This is the most important improvement over naive amount extraction.**

Documents contain many numbers that are NOT monetary amounts:
- Dates: "2026-01-20" → extracts 2026, 1, 20
- Reference numbers: "BH-10021" → extracts 10021
- PO numbers: "PO-7713" → extracts 7713
- Percentages: "VAT 10%" → extracts 10

If you extract ALL numbers, you risk creating **spurious golden triplets** from noise. For example, if a document has amounts [128, 204, 1408] and noise numbers [2026, 10021], you might accidentally find a triplet like 204 + 2026 = 2230 (not in the list, but you get the idea).

**Solution**: Extract amounts with their line context, then filter.

### Date Line Filtering

**Critical**: Date lines must be filtered out entirely before amount extraction. Date lines like "Issue Date: 2026.02-11" contain numbers with decimal points (2026.02) that pass the "has decimal point" filter but are NOT monetary amounts.

```python
def is_date_line(line):
    """Check if a line contains date-like patterns."""
    date_patterns = [
        r'\bdate\b',
        r'\bissued\b',
        r'\bdispatch\b',
        r'\bservice\s+date\b',
        r'\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}',  # YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
        r'\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4}',  # DD-MM-YYYY, etc.
    ]
    line_lower = line.lower()
    return any(re.search(p, line_lower) for p in date_patterns)
```

**Why this matters**: In iteration 2, the number "2026.02" from "Issue Date: 2026.02-11" leaked through the context filter because it has a decimal point. While this didn't cause misclassification in v01, in variants with more documents or noisier OCR, date numbers could create spurious golden triplets.

**Always skip date lines entirely** before extracting amounts.

```python
def extract_amounts_with_context(text):
    amounts_with_context = []
    lines = text.split('\n')
    
    monetary_keywords = [
        'total', 'amount', 'due', 'tax', 'vat', 'gst', 'subtotal',
        'net', 'charges', 'price', 'cost', 'fee', 'payment', 'balance',
        'retainer', 'services', 'order', 'freight', 'meals', 'approved',
        'grand', 'payable', 'outstanding', 'prior', 'estimated', 'requested',
        'included', 'pet', 'paid'
    ]
    
    for line in lines:
        line_lower = line.lower()
        
        # CRITICAL: Skip date lines entirely - they contain noise numbers
        if is_date_line(line):
            continue
        
        has_monetary_context = any(kw in line_lower for kw in monetary_keywords)
        
        numbers = re.findall(r'(\d+(?:\.\d{1,2})?)', line)
        
        for num_str in numbers:
            try:
                num = float(num_str)
                if num > 0.005:  # Skip tiny numbers
                    # Keep if it has monetary context OR has decimal point
                    if has_monetary_context or '.' in num_str:
                        amounts_with_context.append((num, line_lower))
            except ValueError:
                pass
    
    return amounts_with_context
```

**Why this works**:
- Numbers on lines with monetary keywords are likely monetary amounts
- Numbers with decimal points (e.g., "751.68") are likely monetary even without keywords
- Numbers without context and without decimals (e.g., "2026", "10021") are filtered out

### Golden Triplet Detection

For all filtered amounts, find triplets (a, b, c) where:
- a + b ≈ c (within tolerance 0.02)
- c is the largest value (it's the total)

Return all such triplets as candidates.

### Disclaimer Detection

Explicit disclaimers override even the presence of a golden triplet. Check for OCR-tolerant patterns:

**Payment confirmations (receipts)**:
- `card\s+\w+\s+(approved|aproved|aeproved)` — handles "card fayment aeproved"
- `total\s+(paid|pe?t)` — handles "total pet"
- `recei[cpb]t` — handles "receict", "receibt"
- `recei[cg]ht` — more OCR variants

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

**1. Score each triplet using context-based label proximity**:

```python
def score_triplet(triplet, amounts_with_context):
    tax_val, subtotal_val, total_val = triplet
    score = 0
    
    # Check each amount's context for relevant labels
    for amt, ctx in amounts_with_context:
        # Total value near total-related labels
        if abs(amt - total_val) < 0.01:
            if any(kw in ctx for kw in ['total', 'due', 'grand', 'payable', 'amount', 'pet']):
                score += 5
        
        # Tax value near tax-related labels
        if abs(amt - tax_val) < 0.01:
            if any(kw in ctx for kw in ['tax', 'vat', 'gst', 'ast', 'sales', 'included']):
                score += 5
        
        # Subtotal value near subtotal-related labels
        if abs(amt - subtotal_val) < 0.01:
            if any(kw in ctx for kw in ['subtotal', 'subtotat', 'net charges', 'retainer', 
                                        'services', 'order', 'freight']):
                score += 4
    
    # Prefer triplets where tax < subtotal
    if tax_val < subtotal_val:
        score += 2
    
    # Prefer plausible tax rates (3% - 30%)
    if subtotal_val > 0:
        rate = tax_val / subtotal_val
        if 0.03 <= rate <= 0.30:
            score += 3
    
    # Prefer larger amounts (more likely real invoice amounts)
    score += min(total_val / 1000, 2)
    
    return score
```

**2. Select best triplet and extract values**:
- `vat_amount = smaller addend` (the tax)
- `total_amount = sum` (the total)

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
- Context-aware filtering prevents spurious triplets from noise numbers

### document_modality_and_ocr_noise
- **Multiple OCR passes with different PSM modes maximize text capture** (CRITICAL)
- Comma normalization handles varied number formatting
- Context-aware amount filtering reduces noise from dates, reference numbers
- Mathematical cross-validation repairs OCR errors in individual fields

### financial_field_expression
- Golden triplet doesn't rely on field labels at all
- Context-based scoring uses label proximity only as a tiebreaker
- Fallback patterns cover common labels: total, amount due, grand total, VAT, tax, GST, subtotal, net charges
- Mathematical inference recovers missing fields (vat = total - subtotal)
- European number format detection handles "1.280,00" vs "1,280.00"

### batch_scale_and_class_balance
- Algorithm is O(n) per document for classification
- Golden triplet detection is O(m³) where m is number of filtered amounts (typically small after context filtering)
- Scales to any batch size
- Works for invoice-heavy or other-heavy mixes

## Common Pitfalls and Solutions

### Pitfall 1: Using only one OCR PSM mode
**Problem**: Different PSM modes capture different text. Using only PSM 6 might miss text that PSM 11 or 3 would capture.

**Solution**: Always use multiple PSM modes (6, 3, 4, 11, 12) and combine outputs. This is not optional — it's critical for robustness.

### Pitfall 2: Extracting ALL numbers without filtering
**Problem**: Documents contain dates (2026), reference numbers (10021), PO numbers (7713). These can create spurious golden triplets.

**Solution**: Extract amounts with context. Keep numbers that have monetary keywords on the same line OR have decimal points. Filter out the rest.

### Pitfall 3: Regex alternation ordering
**Problem**: Pattern `\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?` matches "105" from "1058.40" then "8.40" separately.

**Solution**: Normalize text by stripping commas first, then use simple pattern `(\d+(?:\.\d{1,2})?)`.

### Pitfall 4: Title-based classification
**Problem**: "Remittance Notice" sounds like a payment confirmation but has full invoice structure. "Payment Reminder" has amounts but explicitly disclaims invoice status.

**Solution**: Use mathematical structure (golden triplet) as primary signal, disclaimers as override. Never classify based on title alone.

### Pitfall 5: OCR noise in numbers
**Problem**: "VAT Inctuded 483" should be "4.83" but OCR dropped decimal point.

**Solution**: Mathematical cross-validation. If subtotal=49.27 and total=54.10, then vat=54.10-49.27=4.83, not 483.

### Pitfall 6: Receipt vs Invoice
**Problem**: Receipts have amounts and may even form golden triplets, but they confirm payment already made, not demand payment.

**Solution**: Detect receipt signals: "card payment approved", "total paid", "receipt" (with OCR variants). These override golden triplets.

### Pitfall 7: Purchase Order vs Invoice
**Problem**: POs have subtotal + tax + total structure (golden triplet exists) but are pre-transaction requests, not billing documents.

**Solution**: Detect PO signals: "purchase order", "approval status: pending", "approved spend ceiling". These override golden triplets.

### Pitfall 8: European number format
**Problem**: Some documents use "1.280,00" instead of "1,280.00". After comma stripping, this becomes "1.28000" which parses as 1.28.

**Solution**: Detect European format (pattern `\d+\.\d{3},\d{2}`) and swap separators before normalization.

### Pitfall 9: Date numbers leaking through context filter
**Problem**: Date lines like "Issue Date: 2026.02-11" contain numbers with decimal points (2026.02) that pass the "has decimal point" filter but are NOT monetary amounts.

**Solution**: Filter out date lines entirely before amount extraction. Use `is_date_line()` to detect lines containing date keywords or date patterns (YYYY-MM-DD, etc.).

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
- [ ] Multiple OCR PSM modes were used for image extraction
- [ ] Amount extraction used context-aware filtering

## Reference Implementation

See `process.py` in the skill package for a complete working implementation of this methodology. The reference implementation includes:
- Multi-PSM OCR extraction
- Context-aware amount filtering
- Golden triplet detection with context-based scoring
- OCR-tolerant disclaimer detection
- Mathematical cross-validation
- Fallback keyword-based extraction
