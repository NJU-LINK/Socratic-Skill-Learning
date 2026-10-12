---
name: financial-document-processor
description: Process mixed batches of financial documents (PDFs and images) by extracting text via OCR/PDF parsing, classifying documents as invoices or non-invoices based on functional content analysis, extracting financial amounts with arithmetic cross-validation, and organizing outputs into structured directories with summary reports.
---

# Financial Document Processor

## Overview

This skill processes batches of mixed financial documents (PDFs and images with opaque filenames) by:
1. Extracting text from PDFs and images (handling OCR noise)
2. Classifying each document as `invoice` or `other` based on functional content
3. Extracting `total_amount` and `vat_amount` from invoices
4. Organizing files into output directories
5. Generating a summary CSV with per-invoice rows and totals

## Core Principles

### 1. Functional Classification Over Header Matching

**Key insight**: Classify documents by what they functionally DO, not by their title or header.

An invoice is a seller→buyer document that requests payment for specific goods/services with amounts. A document titled "Tax Document" may still be an invoice if it functionally requests payment.

**Classification strategy**:

**Step 1: Check for absolute negatives** (documents that are never invoices):
- `not a tax invoice` (explicit disclaimer)
- `approval status: pending` (not yet a valid financial document)

**Step 2: Check for payment status** (temporal distinction):

The core question: Is this document **requesting payment** (invoice) or **confirming payment already made** (receipt/other)?

- **Payment requested** (invoice indicators): `amount due`, `payable total`, `please remit`, `please pay`, `due date`
- **Payment already made** (non-invoice indicators): `total paid`, `card payment approved`, `payment received`, `paid`

**Receipts**: Always `other` because they confirm payment already made, not requesting payment.
- Signals: "Total Paid", "Card Payment Approved", "Payment Received"

**Step 3: Check directionality** for ambiguous document types:

The core question: Is this seller→buyer requesting payment, or buyer→seller confirming payment?

- **Seller→buyer signals** (invoice indicators): `ship to`, `sold to`, `customer`, `bill to`, `amount due`, `please remit`, `payable total`
- **Buyer→seller signals** (non-invoice indicators): `paid by`, `from`, `submitted by`, `reimbursement`, `payment confirmation`

**Ambiguous document types** (require directionality check):

**Remittance notice/advice**: Can be invoice (seller→buyer) OR payment confirmation (buyer→seller).
- The decisive signal is whether it **requests payment** or **confirms payment**:
  - Seller→buyer (payment being requested): "payable total", "ship to", "amount due", "due date"
    - Example: "Payable Total: 2,646.00" + "Ship To: Linden Works" = seller requesting payment → `invoice`
  - Buyer→seller (payment being confirmed): "remitted", "payment date", "paid by", "payment confirmation"
    - Example: "Remitted: 2,646.00" + "Payment Date: 2026-02-02" = buyer confirming payment → `other`
- Note: "Dispatch Date" in a remittance refers to the dispatch of goods/order, not payment. Check for "Payable Total" + "Ship To" to determine if it's requesting payment.

**Purchase order**: Usually buyer→seller request, but if it contains "amount due" + seller→buyer signals, may function as invoice.

**Expense reimbursement**: Usually employee→employer, so `other`.

**Payment reminder**: A chase/dunning letter about a **prior** invoice, not a new invoice itself. Always `other` regardless of disclaimers.
- Signals: "Payment Reminder", "Outstanding Balance", "Total Due This Week"

**Step 4: Check for positive signals** (strong invoice indicators):
- `invoice`, `charge note`, `billing statement`
- `amount due`, `total due`, `grand total`, `please remit`
- `bill to`, `tax document`, `payable total`

**Step 5: Fallback for unknown document types**:
If no patterns match, use a conservative heuristic:
- If the document has monetary amounts AND transaction signals (customer, client, bill to, ship to) → likely `invoice`
- Otherwise → `other` (conservative default)

This handles unseen document types by looking for the structural signature of an invoice (money + counterparty) rather than relying on specific labels.

### 2. OCR Noise Handling via Arithmetic Cross-Validation

OCR output is inherently noisy. Use the arithmetic relationship between subtotal, tax, and total as a validation signal:

**Cross-check**: `subtotal + tax ≈ total`

If the extracted values don't satisfy this relationship (within tolerance ~0.02), the OCR likely misread a value. Common errors:
- Decimal points dropped: "493" instead of "4.93"
- Rates captured instead of amounts: "10" instead of "128.00"

**Recovery strategy**:
1. Extract all three values (subtotal, tax, total) using flexible regex
2. Verify arithmetic consistency
3. If inconsistent, recompute the missing/wrong value from the other two
4. If only subtotal and total are available, compute tax as `total - subtotal`

### 3. Flexible Text Extraction

**For PDFs**: Use PyMuPDF (fitz) for reliable text extraction from embedded text.

**For images**: Use pytesseract with multiple PSM (Page Segmentation Mode) modes:
- PSM 6: Assume a single uniform block of text
- PSM 11: Sparse text, no particular order
- PSM 3: Fully automatic

**Best-pass selection**: Don't just pick the longest text. Instead:
- Extract candidate amounts from each PSM pass
- Score each pass by arithmetic consistency
- Select the pass where `subtotal + tax ≈ total` is most consistent
- Fall back to longest text only if no pass has good arithmetic

### 4. Flexible Regex Patterns

OCR noise means labels may be misspelled or separators may vary.

**Subtotal patterns** (handle OCR variants like "Sublotat", "Subtott"):
```python
r'sub\w+[\s:.]*([\d,]+\.?\d*)'  # Matches "sub" followed by any word chars
```

**Tax/VAT patterns** (handle flexible separators):
```python
# Rate followed by amount: "VAT 10%: 128.00"
r'(?:vat|gst|tax)\s+\d+(?:\.\d+)?\%[\s:.]*([\d,]+\.?\d+)'

# Direct amount: "VAT Included 4.93", "Tax: 55.68", "GST. 78.40"
r'(?:vat|gst|sales\s+tax|tax)[\s:.]*([\d,]+\.\d{2})'
```

**Separator class**: `[\s:.]*` accepts colon, period, space, or nothing.

**Total patterns**:
```python
r'(?:total\s+due|grand\s+total|amount\s+due|total\s+paid|payable\s+total|invoice\s+total)[\s:.]*([\d,]+\.?\d*)'
```

## Implementation Pattern

### Text Extraction

```python
def extract_text(filepath):
    """Extract text based on file extension."""
    if filepath.suffix.lower() == '.pdf':
        return extract_text_pdf(filepath)
    elif filepath.suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
        return extract_text_image(filepath)
    else:
        return ""

def extract_text_pdf(filepath):
    """Extract text from PDF using PyMuPDF."""
    import fitz
    doc = fitz.open(str(filepath))
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

def extract_text_image(filepath):
    """Extract text from image using pytesseract with multiple PSM modes."""
    from PIL import Image
    import pytesseract
    
    img = Image.open(str(filepath))
    # Enlarge 2x for better OCR on noisy scans
    img_large = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    
    results = []
    for psm in [6, 11, 3]:
        text = pytesseract.image_to_string(img_large, config=f'--psm {psm}')
        results.append(text)
    
    # Select best result by arithmetic consistency
    return select_best_ocr_pass(results)
```

### Classification

```python
def classify_document(text):
    """Classify as 'invoice' or 'other' based on functional content."""
    text_lower = text.lower()
    
    # Step 1: Absolute negatives (never invoices)
    absolute_negatives = [
        r'not\s+a\s+tax\s+invoice',
        r'approval\s+status\s*:\s*pending',
    ]
    for pattern in absolute_negatives:
        if re.search(pattern, text_lower):
            return 'other'
    
    # Step 2: Check payment status (temporal distinction)
    # Receipts confirm payment already made → other
    payment_made_patterns = [
        r'total\s+paid',
        r'card\s+payment\s+approved',
        r'payment\s+received',
    ]
    for pattern in payment_made_patterns:
        if re.search(pattern, text_lower):
            return 'other'
    
    # Payment reminder: chase/dunning letter about prior invoice → other
    if re.search(r'payment\s+reminder', text_lower):
        return 'other'
    
    # Expense reimbursement: usually employee→employer → other
    if re.search(r'expense\s+reimbursement', text_lower):
        return 'other'
    
    # Step 3: Check directionality for ambiguous types
    
    # Remittance: check if requesting payment or confirming payment
    if re.search(r'remittance\s+(notice|advice)', text_lower):
        # Seller→buyer signals (payment being requested)
        seller_to_buyer = [
            r'payable\s+total',
            r'ship\s+to',
            r'amount\s+due',
            r'due\s+date',
        ]
        for pattern in seller_to_buyer:
            if re.search(pattern, text_lower):
                return 'invoice'
        
        # Buyer→seller signals (payment being confirmed)
        buyer_to_seller = [
            r'remitted',
            r'payment\s+date',
            r'paid\s+by',
            r'payment\s+confirmation',
        ]
        for pattern in buyer_to_seller:
            if re.search(pattern, text_lower):
                return 'other'
        
        # Default: remittance without clear signals → other
        return 'other'
    
    # Step 4: Positive signals for invoice
    invoice_patterns = [
        r'\binvoice\b',
        r'charge\s+note',
        r'billing\s+statement',
        r'amount\s+due',
        r'total\s+due',
        r'grand\s+total',
        r'please\s+remit',
        r'bill\s+to\b',
        r'tax\s+document',
        r'payable\s+total',
    ]
    
    for pattern in invoice_patterns:
        if re.search(pattern, text_lower):
            return 'invoice'
    
    return 'other'
```

### Financial Field Extraction

```python
def extract_financial_fields(text):
    """Extract total_amount and vat_amount with arithmetic cross-validation."""
    subtotal, vat, total = extract_amounts_raw(text)
    
    # Arithmetic cross-check
    if subtotal is not None and vat is not None and total is not None:
        expected_total = round(subtotal + vat, 2)
        if abs(expected_total - total) > 0.02:
            # Recompute VAT from total - subtotal
            recomputed_vat = round(total - subtotal, 2)
            if recomputed_vat > 0:
                vat = recomputed_vat
    
    # If we have total and subtotal but no VAT, compute it
    if vat is None and total is not None and subtotal is not None:
        computed_vat = round(total - subtotal, 2)
        if computed_vat > 0:
            vat = computed_vat
    
    return total, vat

def extract_amounts_raw(text):
    """Extract subtotal, vat, and total using flexible patterns."""
    lines = text.split('\n')
    subtotal = None
    vat = None
    total = None
    
    sep = r'[\s:.]*'  # Flexible separator
    
    # Extract total
    for line in lines:
        m = re.search(r'(?:total\s+due|grand\s+total|amount\s+due|total\s+paid|payable\s+total|invoice\s+total)' + sep + r'([\d,]+\.?\d*)', line, re.I)
        if m:
            val = parse_amount(m.group(1))
            if val is not None and val > 0:
                total = val
                break
    
    # Extract subtotal (flexible for OCR variants)
    for line in lines:
        m = re.search(r'sub\w+' + sep + r'([\d,]+\.?\d*)', line, re.I)
        if m:
            val = parse_amount(m.group(1))
            if val is not None and val > 0:
                subtotal = val
                break
    
    if subtotal is None:
        for line in lines:
            m = re.search(r'net\s+charges' + sep + r'([\d,]+\.?\d*)', line, re.I)
            if m:
                val = parse_amount(m.group(1))
                if val is not None and val > 0:
                    subtotal = val
                    break
    
    # Extract VAT/tax (avoid capturing rates)
    for line in lines:
        # Rate followed by amount: "VAT 10%: 128.00"
        m = re.search(r'(?:vat|gst|tax)\s+\d+(?:\.\d+)?\%' + sep + r'([\d,]+\.?\d+)', line, re.I)
        if m:
            val = parse_amount(m.group(1))
            if val is not None and val > 0:
                vat = val
                break
    
    if vat is None:
        for line in lines:
            # Direct amount: "VAT Included 4.93", "Tax: 55.68"
            m = re.search(r'(?:vat|gst|sales\s+tax|tax)' + sep + r'([\d,]+\.\d{2})', line, re.I)
            if m:
                val = parse_amount(m.group(1))
                if val is not None and val > 0:
                    vat = val
                    break
    
    return subtotal, vat, total

def parse_amount(text):
    """Parse monetary amount, handling commas and decimals."""
    text = text.strip().replace(',', '').replace('€', '').replace('£', '').replace('$', '')
    try:
        return float(text)
    except ValueError:
        return None
```

### File Organization and Summary

```python
def process_documents(docs_dir, invoices_dir, other_dir, summary_path):
    """Process all documents and generate summary."""
    import csv
    import shutil
    from pathlib import Path
    
    # Create output directories
    invoices_dir.mkdir(parents=True, exist_ok=True)
    other_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each document
    files = sorted([f for f in docs_dir.iterdir() if f.is_file()])
    invoices = []
    
    for filepath in files:
        text = extract_text(filepath)
        classification = classify_document(text)
        
        if classification == 'invoice':
            total_amount, vat_amount = extract_financial_fields(text)
            invoices.append((filepath.name, total_amount, vat_amount))
            shutil.move(str(filepath), str(invoices_dir / filepath.name))
        else:
            shutil.move(str(filepath), str(other_dir / filepath.name))
    
    # Write summary CSV
    with open(summary_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])
        
        total_sum = 0.0
        vat_sum = 0.0
        
        for fname, total, vat in invoices:
            total_val = total if total is not None else 0.0
            vat_val = vat if vat is not None else 0.0
            writer.writerow([fname, f"{total_val:.2f}", f"{vat_val:.2f}"])
            total_sum += total_val
            vat_sum += vat_val
        
        # Total row
        writer.writerow(['total', f"{total_sum:.2f}", f"{vat_sum:.2f}"])
```

## Handling Spec Variations

### document_content_patterns
- **Weak invoice markers**: Use flexible regex and functional classification
- **Overlapping vocabulary**: Negative signals checked first to exclude non-invoices
- **Distributed cues**: Extract text from entire document, not just header

### document_modality_and_ocr_noise
- **Noisier OCR**: Multiple PSM modes + arithmetic cross-validation
- **Mixed PDFs**: PyMuPDF handles both embedded text and rendered pages
- **Partial legibility**: Arithmetic relationships allow inference of missing values

### financial_field_expression
- **Different numeric conventions**: Parse amounts with commas, decimals, currency symbols
- **Tax from subtotals**: Compute tax as `total - subtotal` when not explicit
- **Multiple candidates**: Use specific labels (total due, grand total) over generic "total"

### batch_scale_and_class_balance
- **Variable batch sizes**: Process all files in directory, no hardcoded counts
- **Class imbalance**: Classification logic handles any mix of invoices/non-invoices
- **Summary correctness**: Accumulate totals dynamically, not from fixed row counts

## Dependencies

- **Python 3.7+**
- **PyMuPDF (fitz)**: PDF text extraction
- **pytesseract**: OCR for images
- **Pillow (PIL)**: Image processing
- **tesseract-ocr**: System dependency for pytesseract

**Environment Setup**:
```bash
# Check for Python
which python3

# Install Python packages (use python3 -m pip, not pip)
python3 -m pip install PyMuPDF pytesseract Pillow

# System dependency (Ubuntu/Debian)
which tesseract || sudo apt-get install -y tesseract-ocr
```

**Note**: The environment may have packages pre-installed in a virtual environment. Check with `python3 -c "import fitz; import pytesseract; from PIL import Image; print('OK')"` before installing.

## Reference Implementation

A complete, working reference script is provided as `process_documents.py` in this skill package.

**Usage**:
```bash
# Copy the reference script to /app
cp /skill/financial-document-processor/process_documents.py /app/process.py

# Run it
python3 /app/process.py
```

The script implements all the principles described above and handles:
- PDF and image text extraction
- Multi-PSM OCR with arithmetic-based pass selection
- Functional classification with temporal and directionality checks
- Arithmetic cross-validation for OCR noise
- Flexible regex patterns for OCR variants
- Fallback logic for unknown document types

**Adaptation for variants**: If the variant has different directory paths or requirements, modify the configuration constants at the top of the script (DOCS_DIR, INVOICES_DIR, OTHER_DIR, SUMMARY_PATH).

## Validation Checklist

Before finalizing output:
- [ ] All files moved from input directory (input dir is empty)
- [ ] Invoices in `/invoices/`, non-invoices in `/other/`
- [ ] `summary.csv` has correct columns: `filename`, `total_amount`, `vat_amount`
- [ ] Each invoice has a row with extracted amounts
- [ ] Final row has `filename='total'` with summed amounts
- [ ] Arithmetic cross-check: sum of individual totals = total row total
- [ ] No non-invoices included in summary
