---
name: financial-document-processor
description: Process mixed batches of financial documents (PDFs and images) by classifying them as invoices or non-invoices based on content analysis, extracting financial fields from invoices, organizing files into appropriate directories, and generating summary reports.
---

# Financial Document Processor

This skill handles the classification, extraction, and organization of mixed financial document batches containing invoices and other business documents in PDF and image formats.

## Core Workflow

1. **Extract text** from all documents (pdftotext for PDFs, multi-variant tesseract for images)
2. **Classify** each document as `invoice` or `other` using priority cascade
3. **Extract financial fields** from invoices using arithmetic validation
4. **Organize files** by moving invoices to `/app/invoices/` and others to `/app/other/`
5. **Generate summary** CSV with invoice details and totals

## Document Classification: Priority Cascade

Classification uses a **priority cascade** (not flat keyword scoring) to handle adversarial cases where non-invoices contain overlapping financial vocabulary.

### Priority 1: Explicit Disclaimers (immediate "other")

Check for phrases that explicitly deny invoice status:
- "not a tax invoice"
- "not an invoice"
- "this notice is not"

If any disclaimer is found → classify as `other` immediately.

### Priority 2: Document Type Detection (Check ENTIRE text, not just header)

**Critical: Check the entire document text for receipt indicators, not just the first 5 lines.** OCR may place "receipt" anywhere in the text, and misspellings are common.

Examine the entire text for known non-invoice document types:
- **"receipt"** (and OCR variants) — proof of payment already made (NOT a request for payment)
- "payment reminder" — references outstanding balance, not a new invoice
- "purchase order" — pre-transaction request, not a bill
- "expense reimbursement" / "reimbursement summary" — internal document
- "remittance advice" — payment notification from payer

**OCR-tolerant receipt patterns** (check entire text):
- `recei[gp]t`, `rece[il]pt`, `rec[eo]ipt`, `receipt`
- `rec[ie]p[ts]`, `rec[ie][gp]t`, `rec[ie][il]t`

**Payment completion indicators** (receipts show completed payments):
- "card payment approved"
- "total paid"
- "payment approved"
- "paid in full"

If any of these patterns match → classify as `other`.

**Critical distinction: Receipt vs Invoice**
- **Invoice**: A billing document that *requests* payment from a customer (e.g., "Amount Due", "Please remit")
- **Receipt**: Proof that payment was *already made* (e.g., "Total Paid", "Card Payment Approved")

Receipts contain financial totals but are not invoices because they record completed transactions, not outstanding obligations.

### Priority 3: Invoice Indicator Scoring

Score positive indicators (threshold ≥ 2):

| Indicator | Score | Examples |
|-----------|-------|---------|
| Invoice keywords | +2 each | "invoice", "bill", "statement", "charge", "tax document", "remittance notice" |
| Payment request | +1 each | "amount due", "total due", "payable total", "please remit", "grand total" |
| Buyer field | +1 | "bill to", "customer", "client" |
| Financial structure | +2 | Has subtotal-like label AND tax label AND total label |

**Note:** Receipt keywords are NOT scored here because receipts are classified as "other" in Priority 2.

### Key Insights: Adversarial Classification Cases

1. **Payment Reminders** contain "Total Due", "Tax Amount", "Customer" — all invoice indicators. Only the priority cascade (disclaimer check first, then title check) correctly classifies them as `other`.

2. **Receipts** contain subtotal, tax, total — the full financial structure of an invoice. But they represent *completed* transactions ("Total Paid", "Card Payment Approved"), not outstanding obligations. They must be caught in Priority 2 before keyword scoring.

## Financial Field Extraction

### Strategy: Arithmetic Validation as Backbone

The fundamental technique is **arithmetic consistency**: `subtotal + tax = total`. This solves both OCR noise and multiple-candidate ambiguity simultaneously.

### Step 1: Extract All Label-Number Pairs

For each line in the text, extract (label, number) pairs:
```python
# Process line by line to avoid capturing newlines in labels
for line in text.split('\n'):
    match = re.search(r'([A-Za-z][\w ]{1,25}?)\s*[.:\-]?\s*[\$€£]?\s*([\d,]+\.?\d*)', line)
```

### Step 2: Categorize Labels (OCR-Tolerant)

Labels must be matched with OCR-error tolerance:

| Category | OCR-tolerant patterns |
|----------|----------------------|
| Subtotal | `subtot+`, `subtot[ae]?t`, `subt[oe]t`, `subtest`, `sub\s*tot`, `net\s+charge` |
| Tax | `vat`, `tax`, `gst`, `sales\s+tax` |
| Total | `total`, `paid`, `due`, `payable`, `amount` (but NOT if also subtotal or tax) |

### Step 3: Generate Interpretations (Images Only)

For image documents (OCR noise), generate decimal-shift interpretations for each number:
- Original: `num`
- If ≥ 10: also `num / 10` (OCR may have lost decimal point)
- If ≥ 100: also `num / 100` (OCR may have lost decimal point)

**Critical: Do NOT apply decimal-shift to PDF text** — PDFs have clean text, and shifted interpretations create false matches (e.g., 1408 → 14.08 → 1.408).

### Step 4: Cross-Variant Pooling (Images Only)

For images, pool candidates from ALL OCR variants before arithmetic validation:
1. Run multiple OCR configurations (raw + preprocessed, PSM 3/4/6/11/12)
2. Extract label-number pairs from each variant
3. Pool all categorized candidates into a single set
4. Run arithmetic validation on the pooled set

This handles cases where no single OCR variant contains all correct numbers, but the correct values are distributed across variants.

### Step 5: Find Best Arithmetic Triple

Search all (subtotal, tax, total) combinations for the triple with lowest `|subtotal + tax - total|` error. Accept if error < 0.05.

### Step 6: Tax Refinement

When the arithmetic error is small but non-zero (e.g., 0.04 due to OCR noise), **recalculate tax as `total - subtotal`** to get the exact value. This handles cases where OCR never produces the exact tax number but does produce correct subtotal and total.

### Step 7: Fallback Extraction

If arithmetic validation fails:
1. Try direct regex extraction for total and tax fields
2. Handle "VAT 10%: 128.00" pattern (percentage followed by amount)
3. Apply decimal correction if tax > total

### Numeric Parsing

Handle both standard and European formats:
- Standard: "1,280.00" → 1280.00 (comma = thousands separator)
- European: "49,27" → 49.27 (comma = decimal separator, exactly 2 digits after comma)

```python
def parse_number(raw_num):
    if re.match(r'^\d+,\d{2}$', raw_num):
        return float(raw_num.replace(',', '.'))
    return float(raw_num.replace(',', ''))
```

## OCR Strategies for Image and Scanned PDF Documents

### Multi-Variant Extraction (Images)

Generate multiple OCR outputs for each image:
1. **Raw OCR** with PSM modes 3, 4, 6, 11, 12
2. **Preprocessed OCR**: grayscale → contrast enhancement (2x) → sharpen → 2x upscale → PSM 3/4/6/11/12

Pool all variants for classification and extraction.

### Image Preprocessing Pipeline

```python
img_gray = img.convert('L')
enhancer = ImageEnhance.Contrast(img_gray)
img_enhanced = enhancer.enhance(2.0)
img_sharp = img_enhanced.filter(ImageFilter.SHARPEN)
img_large = img_sharp.resize((width * 2, height * 2), Image.LANCZOS)
```

### PDF OCR Fallback (Scanned PDFs)

For PDFs with embedded text, use `pdftotext`. For scanned-image PDFs (no embedded text), fall back to OCR:

```python
def extract_text_from_pdf(pdf_path):
    result = subprocess.run(['pdftotext', pdf_path, '-'], capture_output=True, text=True)
    text = result.stdout.strip()
    
    # Fallback to OCR if pdftotext returns empty or very short text
    if len(text) < 20:
        return ocr_pdf_via_pdftoppm(pdf_path)
    
    return text

def ocr_pdf_via_pdftoppm(pdf_path):
    """Convert PDF to images using pdftoppm, then OCR each page."""
    tmp_dir = tempfile.mkdtemp(prefix='pdf_pages_')
    
    try:
        # pdftoppm outputs PNG files with prefix
        subprocess.run(['pdftoppm', '-png', '-r', '300', pdf_path, f'{tmp_dir}/page'],
                      check=True, capture_output=True)
        
        all_text = []
        for page_file in sorted(os.listdir(tmp_dir)):
            if page_file.endswith('.png'):
                img = Image.open(os.path.join(tmp_dir, page_file))
                all_text.append(pytesseract.image_to_string(img))
        
        return '\n'.join(all_text)
    finally:
        # Clean up temporary files
        if os.path.exists(tmp_dir):
            for f in os.listdir(tmp_dir):
                os.remove(os.path.join(tmp_dir, f))
            os.rmdir(tmp_dir)
```

**Key points:**
- `pdftoppm` is part of poppler-utils (usually installed alongside pdftotext)
- Use 300 DPI for good OCR quality
- Clean up temporary files after processing
- For scanned PDFs, apply the same multi-variant OCR and arithmetic validation as images

## CSV Generation

### Structure

`summary.csv` with columns: `filename`, `total_amount`, `vat_amount`

- One row per invoice (opaque filenames preserved as-is)
- Final row: `filename` = "total", numeric columns are sums
- Non-invoices excluded from CSV
- Round to 2 decimal places

## File Organization

- `/app/documents/` → source directory (must be empty after processing)
- `/app/invoices/` → invoices + summary.csv
- `/app/other/` → non-invoice documents
- Create output directories if needed
- Move (not copy) files

## Implementation Pattern

```python
#!/usr/bin/env python3
import os, shutil, csv, subprocess, re, tempfile
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

# --- Text Extraction ---

def extract_text_from_pdf(pdf_path):
    """Extract text from PDF, with OCR fallback for scanned PDFs."""
    result = subprocess.run(['pdftotext', pdf_path, '-'], capture_output=True, text=True)
    text = result.stdout.strip()
    
    # Fallback to OCR if pdftotext returns empty or very short text
    if len(text) < 20:
        return ocr_pdf_via_pdftoppm(pdf_path)
    
    return text

def ocr_pdf_via_pdftoppm(pdf_path):
    """Convert PDF to images using pdftoppm, then OCR each page."""
    tmp_dir = tempfile.mkdtemp(prefix='pdf_pages_')
    
    try:
        subprocess.run(['pdftoppm', '-png', '-r', '300', pdf_path, f'{tmp_dir}/page'],
                      check=True, capture_output=True)
        
        all_text = []
        for page_file in sorted(os.listdir(tmp_dir)):
            if page_file.endswith('.png'):
                img = Image.open(os.path.join(tmp_dir, page_file))
                all_text.append(pytesseract.image_to_string(img))
        
        return '\n'.join(all_text)
    finally:
        if os.path.exists(tmp_dir):
            for f in os.listdir(tmp_dir):
                os.remove(os.path.join(tmp_dir, f))
            os.rmdir(tmp_dir)

def extract_all_text_variants_from_image(img_path):
    """Generate multiple OCR variants for an image."""
    img = Image.open(img_path)
    variants = []
    for psm in [3, 4, 6, 11, 12]:
        variants.append(pytesseract.image_to_string(img, config=f'--psm {psm}'))
    # Preprocessed variants
    img_gray = img.convert('L')
    img_enhanced = ImageEnhance.Contrast(img_gray).enhance(2.0)
    img_sharp = img_enhanced.filter(ImageFilter.SHARPEN)
    img_large = img_sharp.resize((img_sharp.width * 2, img_sharp.height * 2), Image.LANCZOS)
    for psm in [3, 4, 6, 11, 12]:
        variants.append(pytesseract.image_to_string(img_large, config=f'--psm {psm}'))
    return variants

# --- Classification ---

def classify_document(text):
    text_lower = text.lower()
    lines = text.strip().split('\n')
    
    # Priority 1: Disclaimers
    for p in [r'not\s+a\s+tax\s+invoice', r'not\s+an\s+invoice', r'this\s+notice\s+is\s+not']:
        if re.search(p, text_lower): return 'other'
    
    # Priority 2: Check ENTIRE text for receipt indicators (not just header)
    # OCR-tolerant receipt patterns
    receipt_patterns = [
        r'recei[gp]t', r'rece[il]pt', r'rec[eo]ipt', r'receipt',
        r'rec[ie]p[ts]', r'rec[ie][gp]t', r'rec[ie][il]t'
    ]
    for p in receipt_patterns:
        if re.search(p, text_lower): return 'other'
    
    # Payment completion indicators (receipts show completed payments)
    payment_completion = [
        r'card\s+payment\s+approved',
        r'total\s+paid',
        r'payment\s+approved',
        r'paid\s+in\s+full'
    ]
    for p in payment_completion:
        if re.search(p, text_lower): return 'other'
    
    # Check header for other non-invoice types
    header = '\n'.join(lines[:5]).lower()
    for t in ['payment reminder', 'purchase order', 'expense reimbursement', 'reimbursement summary']:
        if t in header: return 'other'
    
    # Priority 3: Scoring (no receipt keywords here - they're already excluded)
    score = 0
    for kw in ['invoice', 'bill', 'statement', 'charge', 'tax document', 'remittance notice']:
        if kw in text_lower: score += 2
    for p in [r'amount\s+due', r'total\s+due', r'payable\s+total', r'please\s+remit', r'grand\s+total']:
        if re.search(p, text_lower): score += 1
    for p in [r'bill\s+to', r'customer', r'client']:
        if re.search(p, text_lower): score += 1; break
    
    # Financial structure check (OCR-tolerant subtotal patterns)
    sub_pats = [r'subtot+', r'subtot[ae]?t', r'subt[oe]t', r'subtest', r'sub\s*tot']
    has_sub = any(re.search(p, text_lower) for p in sub_pats)
    has_tax = bool(re.search(r'vat|tax|gst', text_lower))
    has_total = bool(re.search(r'total|amount\s+due', text_lower))
    if has_sub and has_tax and has_total: score += 2
    
    return 'invoice' if score >= 2 else 'other'

# --- Field Extraction ---

def parse_number(raw_num):
    if re.match(r'^\d+,\d{2}$', raw_num):
        return float(raw_num.replace(',', '.'))
    return float(raw_num.replace(',', ''))

def is_subtotal_label(label):
    return any(re.search(p, label) for p in [r'subtot+', r'subtot[ae]?t', r'subt[oe]t', r'subtest', r'sub\s*tot', r'net\s+charge'])

def extract_label_number_pairs(text):
    pairs = []
    for line in text.split('\n'):
        m = re.search(r'([A-Za-z][\w ]{1,25}?)\s*[.:\-]?\s*[\$€£]?\s*([\d,]+\.?\d*)', line)
        if m: pairs.append((m.group(1), m.group(2)))
    return pairs

def categorize_pair(label, raw_num, candidates, allow_decimal_shift=True):
    label_lower = label.strip().lower()
    try: num = parse_number(raw_num)
    except: return
    if num <= 0: return
    
    interps = [num]
    if allow_decimal_shift:
        if num >= 10: interps.append(num / 10)
        if num >= 100: interps.append(num / 100)
    
    is_sub = is_subtotal_label(label_lower)
    is_tax = bool(re.search(r'vat|tax|gst|sales\s+tax', label_lower))
    is_total = bool(re.search(r'total|paid|due|payable|amount', label_lower))
    
    if is_total and not is_sub and not is_tax: candidates['total'].extend(interps)
    if is_sub: candidates['subtotal'].extend(interps)
    if is_tax: candidates['tax'].extend(interps)

def find_best_triple(candidates, tolerance=0.05):
    best, best_err = None, float('inf')
    for s in candidates.get('subtotal', []):
        for t in candidates.get('tax', []):
            for g in candidates.get('total', []):
                err = abs(s + t - g)
                if err < best_err: best_err = err; best = (s, t, g)
    if best and best_err < tolerance:
        sub, tax, total = best
        if best_err < 0.1: tax = total - sub  # Refine
        return {'total_amount': round(total, 2), 'vat_amount': round(tax, 2)}
    return None

def extract_fields_pooled(variants):
    candidates = {'subtotal': [], 'tax': [], 'total': []}
    for text in variants:
        for label, raw in extract_label_number_pairs(text):
            categorize_pair(label, raw, candidates, allow_decimal_shift=True)
    result = find_best_triple(candidates)
    if result: return result
    return extract_fields_direct(max(variants, key=len))

def extract_fields_pdf(text):
    candidates = {'subtotal': [], 'tax': [], 'total': []}
    for label, raw in extract_label_number_pairs(text):
        categorize_pair(label, raw, candidates, allow_decimal_shift=False)
    result = find_best_triple(candidates)
    if result: return result
    return extract_fields_direct(text)

def extract_fields_direct(text):
    total = vat = None
    for p in [r'(?:grand\s+)?total(?:\s+due|\s+paid)?[:\.\s]+\$?([\d,]+\.?\d*)',
              r'amount\s+due[:\.\s]+\$?([\d,]+\.?\d*)', r'payable\s+total[:\.\s]+\$?([\d,]+\.?\d*)']:
        m = re.search(p, text, re.I)
        if m: total = parse_number(m.group(1)); break
    m = re.search(r'(?:vat|tax|gst|sales\s+tax)\s+\d+%?\s*[:\.\s]+\s*([\d,]+\.?\d*)', text, re.I)
    if m: vat = parse_number(m.group(1))
    else:
        for p in [r'(?:vat|tax|gst|sales\s+tax)[:\.\s]+\$?([\d,]+\.?\d*)', r'(?:vat|tax)\s+included[:\.\s]+\$?([\d,]+\.?\d*)']:
            m = re.search(p, text, re.I)
            if m: vat = parse_number(m.group(1)); break
    return {'total_amount': round(total, 2) if total else None, 'vat_amount': round(vat, 2) if vat else None}
```

## Variation Handling (spec axes)

### document_content_patterns
- **Weak invoice markers**: Use financial structure detection (subtotal + tax + total pattern) rather than just keywords
- **Overlapping vocabulary**: Priority cascade ensures disclaimers and title types are checked before keyword scoring
- **Multi-region cues**: Classification combines header, body, and financial structure signals

### document_modality_and_ocr_noise
- **Noisy OCR**: Multi-variant pooling + arithmetic validation handles garbled labels and numbers
- **Mixed PDFs**: pdftotext for text PDFs; OCR fallback (pdftoppm + tesseract) for scanned PDFs; no decimal-shift interpretations for clean text
- **Partial legibility**: Tax refinement (total - subtotal) recovers exact values when OCR misses tax number

### financial_field_expression
- **Different numeric conventions**: European decimal comma detection (digits,digits → decimal)
- **Implicit tax**: Arithmetic validation derives tax from subtotal + tax = total
- **Multiple candidates**: Arithmetic triple selection picks the consistent set from many candidates

### batch_scale_and_class_balance
- **Small/large batches**: Same workflow, CSV sums scale correctly
- **Imbalanced mixes**: Classification logic works regardless of invoice/other ratio

## Validation Checklist

- [ ] All documents moved from `/app/documents/` (directory is empty)
- [ ] Invoices in `/app/invoices/`, others in `/app/other/`
- [ ] `summary.csv` in `/app/invoices/` with columns: filename, total_amount, vat_amount
- [ ] One row per invoice + "total" row with correct sums
- [ ] Financial amounts validated: subtotal + tax ≈ total
- [ ] No documents lost or duplicated
