---
name: financial-document-processor
description: Classify mixed financial documents (invoices vs other types), extract monetary fields from invoices, and generate summary reports. Handles PDFs and images with OCR noise, fuzzy document markers, and varying financial field expressions.
---

# Financial Document Processor

Process batches of mixed financial documents by classifying them, extracting monetary fields, and generating structured summaries.

## Quick Start

The skill package is mounted at `/skill/` inside the container. To process documents:

```bash
python /skill/scripts/process_documents.py \
  --source /app/documents \
  --invoices /app/invoices \
  --other /app/other
```

This will:
- Classify each document as `invoice` or `other` using multi-signal analysis
- Extract `total_amount` and `vat_amount` from invoices
- Move files to appropriate directories
- Create `/app/invoices/summary.csv` with per-invoice rows and totals

## Core Task Structure

1. **Input**: Directory of documents (PDF + image files) with opaque filenames
2. **Classification**: Determine if each document is an `invoice` or `other` based on content
3. **Extraction**: For invoices, extract `total_amount` (final amount including tax) and `vat_amount` (tax/VAT/GST)
4. **Routing**: Move invoices to one directory, non-invoices to another
5. **Summary**: Create CSV with per-invoice rows plus a total row

## Critical Design Principles

### 1. Multi-Signal Classification (Not Keyword-Only)

**Problem**: Keyword-based classification fails when OCR garbles document titles or when documents use non-standard terminology.

**Solution**: Use three independent signal classes:

#### A. Mathematical Consistency (Strongest Signal)
- Extract all labeled monetary amounts from the document
- Check if any two amounts sum to a third: `subtotal + tax ≈ total`
- This relationship survives OCR noise because numbers are often readable even when text isn't
- Tolerance: ±2.0 to handle OCR errors in numeric values
- **Invoice indicator**: If mathematical consistency exists AND payment is being requested (not already made)

#### B. Payment Direction Analysis
- **"Due" signals** (invoice): `total due`, `amount due`, `payable`, `balance due`, `please remit`
- **"Paid" signals** (receipt/other): `total paid`, `payment approved`, `receipt`
- An invoice requests payment; a receipt confirms payment was made
- Both may have subtotal + tax structure, so direction is the differentiator

#### C. Fuzzy Keyword Matching
- Document type indicators: `invoice`, `billing statement`, `charge note`, `tax document`, `remittance notice`
- Use OCR-tolerant patterns that handle common errors:
  - Character substitutions: o↔a, n↔r, e↔a (e.g., "charge nate" for "charge note")
  - Multiple pattern variants for each keyword
- Score-based: require multiple positive signals (threshold ≥ 3 points)

#### D. Strong Negative Signals (Override Everything)
- Explicit disclaimers: `not an invoice`, `not a tax invoice`
- Non-invoice document types: `payment reminder`, `purchase order`, `expense reimbursement`, `receipt`
- Approval status: `pending approval` (indicates purchase order, not invoice)

### 2. OCR Noise Tolerance

**Problem**: OCR introduces errors in both text and numbers. Different OCR passes may give different results.

**Solution**:

#### Multiple OCR Passes
- For images, run 3 OCR approaches:
  1. Default configuration
  2. Grayscale + enhanced contrast + PSM 6
  3. Original image + PSM 4
- Use the longest text for keyword analysis
- Check mathematical consistency across ALL variants (a relationship that appears in any variant is likely real)

#### Flexible Amount Parsing
- Handle multiple numeric formats:
  - Standard: `1,234.56` (comma = thousands, period = decimal)
  - European: `1.234,56` (period = thousands, comma = decimal)
  - No separator: `1234.56` or `1234,56`
- Use comprehensive regex that captures full amounts including thousands separators
- Deduplicate amounts that match multiple overlapping patterns

#### Fuzzy Field Extraction
- For tax/VAT fields, accept OCR variants: `vat`, `tax`, `gst`, `ast` (common OCR error for "vat")
- If direct extraction fails, compute: `vat_amount = total_amount - subtotal`
- Try multiple text variants and use the first that yields both values

### 3. Financial Field Extraction Strategy

**Priority order**:

1. **Direct extraction**: Look for explicit labels
   - Total: `grand total`, `total due`, `amount due`, `payable total`, `invoice total`
   - Tax: `vat`, `tax`, `gst`, `sales tax` (with optional rate like "VAT 10%")
   - Subtotal: `subtotal`, `sub total`, `net charges`, `net amount`

2. **Computed values**: If direct extraction fails
   - `total = subtotal + tax` (if both subtotal and tax are found)
   - `tax = total - subtotal` (if both total and subtotal are found)

3. **Rate-based tax recovery** (spec-declared variation): If tax amount is absent but rate is present
   - Extract percentage rates: `VAT 10%`, `GST 20%`, etc.
   - `tax = subtotal × rate / 100` (if subtotal and rate are found)
   - `total = subtotal + tax` (compute total from subtotal + computed tax)
   - `subtotal = total / (1 + rate/100)` (if total and rate are found but subtotal is missing)

4. **Cross-validation**: If multiple candidates exist
   - Prefer values that satisfy mathematical relationships
   - For OCR text, use the largest amount in a "total" context

### 4. Amount Parsing Robustness

**Challenge**: Monetary amounts appear in various formats and OCR may corrupt them.

**Approach**:

```python
def parse_amount(text):
    # Remove currency symbols
    cleaned = re.sub(r'[€$£¥]', '', text).strip()
    
    # Determine format by separator positions
    has_comma = ',' in cleaned
    has_period = '.' in cleaned
    
    if has_comma and has_period:
        last_dot = cleaned.rfind('.')
        last_comma = cleaned.rfind(',')
        if last_comma > last_dot:
            # European: 1.234,56 -> 1234.56
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            # Standard: 1,234.56 -> 1234.56
            cleaned = cleaned.replace(',', '')
    elif has_comma:
        parts = cleaned.split(',')
        if len(parts) == 2 and len(parts[1]) == 2:
            # Decimal comma: 1234,56 -> 1234.56
            cleaned = cleaned.replace(',', '.')
        else:
            # Thousands comma: 1,234 -> 1234
            cleaned = cleaned.replace(',', '')
    
    # Extract numeric value
    match = re.search(r'[\d]+(?:\.\d+)?', cleaned)
    return float(match.group()) if match else 0.0
```

**Extraction regex** (non-overlapping, handles thousands):
```python
pattern = r'\b(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2}|\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})\b'
```

## Running the Implementation

A complete, tested Python implementation is provided at `scripts/process_documents.py`.

**Important**: The skill package is mounted read-only at `/skill/` inside the task container. 

**Accessing skill resources**: Use `task_shell` to read or execute skill files (e.g., `cat /skill/scripts/process_documents.py` or `python /skill/scripts/process_documents.py`). The `read` tool cannot access `/skill/` due to workspace boundaries.

### Basic Usage

```bash
python /skill/scripts/process_documents.py \
  --source /path/to/documents \
  --invoices /path/to/invoices \
  --other /path/to/other
```

### Example for v01 Task

```bash
python /skill/scripts/process_documents.py \
  --source /app/documents \
  --invoices /app/invoices \
  --other /app/other
```

### What the Script Does

1. Scans the source directory for PDF and image files
2. Extracts text using multiple OCR approaches (for images) or pdftotext (for PDFs)
3. Classifies each document using multi-signal analysis
4. Extracts `total_amount` and `vat_amount` from invoices
5. Moves files to appropriate directories
6. Creates `summary.csv` in the invoices directory with per-invoice rows plus a total row

### Dependencies

The script requires:
- Python 3.7+
- `pytesseract` and `Pillow` for OCR (images)
- `pdftotext` command-line tool OR `PyMuPDF` (fitz) for PDFs
- Standard library: `os`, `re`, `csv`, `shutil`, `subprocess`, `argparse`, `pathlib`, `itertools`

## Implementation Workflow (Detailed)

### Step 1: Text Extraction (Implemented in `extract_text()`)

**For PDFs** (3-tier fallback):
1. Primary: `pdftotext` command-line tool (fast, handles embedded text)
2. Secondary: PyMuPDF (`fitz`) `get_text()` (alternative embedded text extraction)
3. Tertiary: OCR fallback — render each PDF page as an image at 200 DPI and run tesseract OCR. This handles scanned PDFs with no embedded text.

**For Images**:
- Use `pytesseract` with multiple configurations
- Apply preprocessing: grayscale conversion, contrast enhancement
- Try multiple PSM (Page Segmentation Mode) settings
- Return all text variants for downstream analysis

### Step 2: Amount Extraction (Implemented in `extract_all_amounts()`)

Extract all monetary amounts with their line context:
```python
amounts = []
for line in text.split('\n'):
    matches = re.findall(amount_pattern, line)
    for match in matches:
        amounts.append({
            'amount': parse_amount(match),
            'line': line.lower()
        })
```

### Step 3: Mathematical Consistency Check (Implemented in `check_mathematical_consistency()`)

```python
def check_math_consistency(amounts):
    values = [a['amount'] for a in amounts]
    if len(values) < 3:
        return False
    
    # Check all triplets: a + b ≈ c
    for a, b, c in combinations(values, 3):
        if abs((a + b) - c) < 2.0:
            return True
    return False
```

### Step 4: Classification (Implemented in `classify_document()`)

Combine signals with scoring:
- Mathematical consistency: +2 points
- Payment direction (due, not paid): +2 points
- Keyword matches: +1 point each (threshold: ≥3 total)
- Strong negative signals: override to "other"

### Step 5: Field Extraction (Implemented in `extract_financial_fields()`)

For each invoice:
1. Try direct extraction with multiple pattern variants
2. If incomplete, compute missing values from relationships
3. Cross-validate across OCR variants
4. Use first variant that yields both total and vat

### Step 6: Output Generation (Implemented in `process_documents()`)

- Move files to appropriate directories
- Create CSV with columns: `filename`, `total_amount`, `vat_amount`
- Add final row: `total`, sum of total_amount, sum of vat_amount
- Format amounts with 2 decimal places

## Handling Spec Variations

### document_content_patterns
- **Weak invoice markers**: Mathematical consistency + payment direction compensate
- **Overlapping vocabulary**: Negative signals (receipt, reminder, purchase order) disambiguate
- **Distributed cues**: Check entire document, not just title/first lines

### document_modality_and_ocr_noise
- **Noisier OCR**: Multiple OCR passes + cross-variant validation
- **Mixed PDF types**: Fallback extraction methods (pdftotext → PyMuPDF)
- **Partially legible fields**: Computed values (total - subtotal = tax)

### financial_field_expression
- **Different numeric conventions**: Robust amount parser handles all formats
- **Computed taxes**: Extract from subtotals/rates when not explicit
- **Rate-based recovery**: Compute tax from subtotal × rate when tax amount is absent
- **Multiple candidates**: Use mathematical relationships to select correct values

### batch_scale_and_class_balance
- **Small/large batches**: Algorithm scales linearly with document count
- **Imbalanced mixes**: Classification doesn't depend on batch composition
- **Summary correctness**: Aggregation works for any number of invoices

## Common Failure Modes & Mitigations

1. **OCR misreads document title** (e.g., "charge note" → "charge nate")
   - **Mitigation**: Fuzzy pattern matching + mathematical consistency check

2. **Thousands separator parsed as decimal** (e.g., "1,280.00" → 1.28)
   - **Mitigation**: Comprehensive regex that captures full amount with separators

3. **Receipt classified as invoice** (both have subtotal + tax structure)
   - **Mitigation**: Payment direction analysis ("paid" vs "due")

4. **VAT not explicitly labeled** (OCR shows "ast" instead of "vat")
   - **Mitigation**: Fuzzy tax patterns + compute from total - subtotal

5. **Mathematical consistency false positive** (duplicate amounts create spurious triplets)
   - **Mitigation**: Deduplicate amounts before checking

6. **Multiple total candidates** (summary sections, subtotals, etc.)
   - **Mitigation**: Prefer amounts in explicit "total due" context; validate with math

7. **Tax amount absent but rate present** (e.g., "VAT 10%" with no amount, only subtotal)
   - **Mitigation**: Extract percentage rate, compute tax = subtotal × rate / 100
   - **Reverse case**: If total + rate present but no subtotal, compute subtotal = total / (1 + rate/100)

## Testing Checklist

- [ ] PDFs with embedded text extract correctly
- [ ] Images with clean OCR classify correctly
- [ ] Images with noisy OCR still classify via mathematical consistency
- [ ] Receipts (proof of payment) classified as "other"
- [ ] Payment reminders classified as "other"
- [ ] Purchase orders classified as "other"
- [ ] Expense reimbursements classified as "other"
- [ ] Invoices with non-standard titles classified correctly
- [ ] Rate-based tax recovery works (tax = subtotal × rate / 100)
- [ ] Reverse rate recovery works (subtotal = total / (1 + rate/100))
- [ ] Thousands separators parsed correctly (1,234.56)
- [ ] European format parsed correctly (1.234,56)
- [ ] VAT extracted when explicitly labeled
- [ ] VAT computed when not explicit (total - subtotal)
- [ ] Summary CSV has correct structure and totals
- [ ] All documents moved (source directory empty)
- [ ] Files preserved (not deleted or corrupted)

## Example Classification Logic

```python
def classify(text_variants, filename):
    primary_text = max(text_variants, key=len)
    
    # Check math consistency across all variants
    has_math = any(
        check_math_consistency(extract_all_amounts(t))
        for t in text_variants
    )
    
    # Strong negatives (override everything)
    if fuzzy_match(r'not\s+(a\s+)?(tax\s+)?invoice', primary_text):
        return 'other'
    if fuzzy_match(r'payment\s+reminder|purchase\s+order|expense\s+reimbursement', primary_text):
        return 'other'
    
    # Receipt check
    is_receipt = fuzzy_match(r'receipt|card\s+payment\s+approved', primary_text)
    has_paid = bool(re.search(r'\b(paid|payment\s+approved)\b', primary_text))
    has_due = bool(re.search(r'\b(due|payable|remit)\b', primary_text))
    
    if is_receipt and has_paid and not has_due:
        return 'other'
    
    # Score positive signals
    score = 0
    if has_math:
        score += 2
    if has_due and not has_paid:
        score += 2
    score += count_invoice_keywords(primary_text)
    
    return 'invoice' if score >= 3 else 'other'
```

## Key Takeaways

1. **Don't rely on keywords alone** — OCR noise and non-standard terminology will break pure keyword matching
2. **Mathematical relationships are robust** — subtotal + tax ≈ total survives OCR errors that garble titles
3. **Payment direction disambiguates** — "due" vs "paid" distinguishes invoices from receipts
4. **Multiple OCR passes help** — Different configurations catch different errors
5. **Compute missing values** — If VAT isn't explicit, calculate from total - subtotal
6. **Handle numeric formats** — Thousands separators and decimal conventions vary globally
7. **Fuzzy matching for OCR errors** — Common character substitutions (o↔a, n↔r) are predictable
