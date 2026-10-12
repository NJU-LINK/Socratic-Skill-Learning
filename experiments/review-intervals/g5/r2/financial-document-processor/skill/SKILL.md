---
name: financial-document-processor
description: Process mixed batches of financial documents (PDFs and images) by classifying them as invoices or other document types, extracting financial amounts from invoices, and generating a summary CSV. Handles OCR noise, varied document formats, and different tax/total expression patterns.
---

# Financial Document Processor

Process a batch of mixed financial documents (PDFs and images) by:
1. Classifying each document as `invoice` or `other`
2. Extracting `total_amount` and `vat_amount` from invoices
3. Moving documents to appropriate folders (`invoices/` and `other/`)
4. Generating `summary.csv` with invoice data and totals

## Core Algorithm

### 1. Text Extraction

**PDFs:** Use `pdftotext` first (fast, accurate). If `pdftotext` returns fewer than 20 characters (indicating a scanned PDF), fall back to OCR:
```python
def extract_text_pdf(fp):
    r = subprocess.run(['pdftotext', str(fp), '-'], capture_output=True, text=True)
    text = r.stdout.strip()
    if len(text) < 20:  # Scanned PDF fallback
        return extract_text_image_pdf(fp)
    return text

def extract_text_image_pdf(fp):
    # Convert PDF pages to PNG images at 300 DPI using pdftoppm
    # Then OCR each page using the image pipeline
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(['pdftoppm', '-png', '-r', '300', str(fp), f'{tmpdir}/page'])
        for img_file in sorted(Path(tmpdir).glob('page-*.png')):
            page_text = extract_text_image(img_file)
            text_parts.append(page_text)
    return '\n'.join(text_parts)
```

**Images (JPG/PNG/TIFF):** Preprocess before tesseract:
```python
img = Image.open(path).convert('L')           # Grayscale
img = ImageOps.autocontrast(img)               # Maximize dynamic range
img = img.resize((img.width*3, img.height*3), Image.LANCZOS)  # Upscale 3x
img = img.filter(ImageFilter.SHARPEN)          # Sharpen
# Save to temp file, then: tesseract temp.png stdout
```

**Critical:** Do NOT binarize images — it loses faint text and makes OCR worse.

### 2. Classification by Scored Cues

Use a **scoring system** rather than hard keyword gates. This handles documents with weak or non-standard invoice markers.

**Hard negatives** (immediately classify as `other`):
- "not a tax invoice", "not an invoice"
- "purchase order", "payment reminder"
- "expense reimbursement", "expense report"
- "approval status.*pending", "reclaimable tax"

**Structural prerequisite gate:** Before scoring, require at least one structural marker. Financial field cues alone (subtotal, tax, total) are necessary but not sufficient — receipts and vouchers also have these. Require:

- **Reference number patterns:** `ref`, `reference`, `invoice no`, `invoice number`, `invoice #`, `order no`, `order number`, `document id`, `doc ref`, `doc no`, `doc number`, `account no`, `account number` followed by alphanumeric ID
- **Date patterns:** `date`, `issued`, `dispatch`, `invoice date` followed by YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, or Month DD, YYYY format
- **Party identifiers:** `bill to`, `ship to`, `sold to`, `deliver to`, `client`, `customer`, `attention`, `attn`

If no structural marker is present, classify as `other` (likely a receipt or voucher).

**Why this matters:** Documents with only bare financial numbers (subtotal, VAT, total) but no reference numbers, dates, or party identifiers are typically receipts, vouchers, or other non-invoice financial documents. The structural prerequisite prevents these from being misclassified as invoices.

**Positive cues** (weighted scoring, threshold ≥ 5):
- High weight (3): "invoice", "billing statement", "charge notes?", "grand total", "payable total"
- Medium weight (2): "tax document", "remittance notice", "amount due", "total due", "total paid", "vat", "sales tax", "gst", "subtotal", "bill to"
- Low weight (1): "ship to", "customer", "client", "doc ref", "issue date"

**OCR normalization:** Before matching, normalize common OCR errors:
```python
replacements = {
    'subtotat': 'subtotal', 'subtotet': 'subtotal', 'subtota1': 'subtotal',
    'inctuded': 'included', 'inctudedct': 'included', 'inc1uded': 'included',
    'taxi': 'tax', 'taxt': 'tax', 'tota1': 'total',
    'suramary': 'summary', 'surmary': 'summary',
    'reimbursemen': 'reimbursement', 'reimbursment': 'reimbursement',
    'eynense': 'expense', 'expence': 'expense',
    'mats': 'notes', 'note5': 'notes',
    'bi11': 'bill', 'sh1p': 'ship',
    'cust0mer': 'customer', 'c1ient': 'client'
}
```

**Common OCR substitutions:** Numbers often misread as letters (0→o, 1→l/i, 5→s) and vice versa. The expanded dictionary handles these variations.

### 3. Amount Extraction with OCR-Decimal Recovery

**The challenge:** OCR often drops decimal points from amounts (e.g., "54.20" → "5420", "4.93" → "493").

**The solution:** Use arithmetic cross-check. In a valid invoice: `subtotal + tax ≈ total`.

**Algorithm:**
1. Extract all labeled amounts (subtotal, vat/tax, total) with their raw strings
2. For each amount without a decimal point, generate candidate values by inserting decimal at different positions:
   - "493" → [493, 49.3, 4.93]
   - "5420" → [5420, 542.0, 54.20, 5.420]
3. Use `itertools.product` to try all combinations
4. Find the combination where `abs(subtotal + tax - total) < 0.02`
5. Prefer the smallest valid total (Occam's razor for invoices)

**VAT regex pitfalls:**
- Must tolerate words between keyword and number: use `[\w\s.%:]*?` bridge
  - Handles: "VAT included 493", "VAT 10%: 128.00", "GST: 78.40"
- Must skip percentage rates: use `\b(?!%)` after capture
  - Prevents capturing "10" from "VAT 10%"
  - The `\b` (word boundary) prevents partial digit matches

**Correct VAT regex:**
```python
r'(?:vat|tax|gst|sales\s+tax)[\w\s.%:]*?\$?([\d,]+\.?\d*)\b(?!%)'
```

**Fallback logic:** If cross-check fails (e.g., only 2 of 3 amounts found):
- If subtotal and total exist but no VAT: `vat = total - subtotal`
- If subtotal and VAT exist but no total: `total = subtotal + vat`

**Critical regex fix:** When matching "total", use `(?<!\w)total` to match standalone "total" but NOT "subtotal". Otherwise, the regex may capture the subtotal value instead of the actual total. The full total pattern should be:
```python
r'(?:grand\s+total|total\s+due|amount\s+due|payable\s+total|total\s+paid|invoice\s+total|(?<!\w)total)[:\s]*\$?([\d,]+\.?\d*)'
```

### 4. Output Generation

Write `summary.csv` with columns: `filename`, `total_amount`, `vat_amount`

**Floating point hygiene:** Always `round()` sums before writing:
```python
w.writerow(['total', round(total_sum, 2), round(vat_sum, 2)])
```

## Handling Spec Variation Axes

### document_content_patterns
- **Weak invoice markers:** Scoring system (not keyword gates) handles documents without "Invoice" in the title
- **Overlapping vocabulary:** Hard negatives distinguish invoices from POs, reminders, expense reports
- **Multi-region cues:** Extract from entire document text, not just headers

### document_modality_and_ocr_noise
- **Mixed file types:** PDF → `pdftotext`, images → preprocessed tesseract
- **Noisy OCR:** Preprocessing pipeline (grayscale, autocontrast, upscale, sharpen) + OCR error normalization dictionary
- **Partial legibility:** Decimal recovery algorithm infers correct values from arithmetic relationships

### financial_field_expression
- **Different total labels:** Regex matches "grand total", "total due", "amount due", "payable total", "total paid", "invoice total"
- **Different tax labels:** Regex matches "vat", "tax", "gst", "sales tax" with flexible bridge
- **Computed tax:** If VAT not explicitly shown, compute from `total - subtotal`
- **Multiple candidates:** Cross-check selects the combination satisfying `subtotal + tax ≈ total`

### batch_scale_and_class_balance
- **Data-driven:** Script processes all PDFs/images in directory, no hardcoded counts
- **Correct totals:** Sum loop handles any number of invoices
- **Empty directories:** Script creates output dirs if needed, handles empty input gracefully

## Implementation Checklist

- [ ] Create output directories (`invoices/`, `other/`)
- [ ] Extract text from each document (PDF vs image)
- [ ] Normalize OCR errors before classification
- [ ] Classify using scored cues (threshold ≥ 5)
- [ ] For invoices: extract amounts with decimal recovery
- [ ] Move files to appropriate directories
- [ ] Write `summary.csv` with invoice rows + total row
- [ ] Round floating-point sums to 2 decimal places
- [ ] Verify `/app/documents/` is empty after processing

## Common Pitfalls

1. **Binarizing images** → loses faint text, makes OCR worse
2. **Hard keyword matching** → fails on documents with non-standard titles
3. **Greedy VAT regex** → captures "10" from "VAT 10%" instead of "128.00"
4. **No decimal recovery** → accepts OCR-garbled amounts like "5420" instead of "54.20"
5. **Floating-point accumulation** → produces "5918.280000000001" instead of "5918.28"
6. **Not normalizing OCR** → "subtotat" doesn't match "subtotal" pattern

## Testing Strategy

1. **Extract all text first** — inspect before writing logic
2. **Manually classify** — verify your reasoning matches the script
3. **Check arithmetic** — for each invoice, verify `subtotal + tax ≈ total`
4. **Test edge cases:**
   - Noisy OCR with dropped decimals
   - Documents with "VAT 10%" (rate) vs "VAT: 128.00" (amount)
   - Non-invoices with financial vocabulary (POs, reminders, expense reports)
   - Invoices without explicit "Invoice" in title
   - Scanned PDFs (should trigger OCR fallback)

## Known Limitations

**Multi-page invoices with totals on later pages:** The current implementation extracts text from all pages but applies classification and amount extraction to the concatenated text. If a multi-page invoice has its total only on page 2 or 3, the extraction should still work, but classification may be less reliable if early pages lack invoice markers. **Mitigation:** The structural prerequisite gate checks the entire concatenated text, so as long as any page has a reference number, date, or party identifier, the document will be classified as invoice.

**Extremely poor OCR quality:** If tesseract produces completely garbled text even after preprocessing (e.g., very low resolution scans, unusual fonts, rotated pages), the decimal recovery algorithm may fail to find a valid `subtotal + tax ≈ total` combination. In such cases, the script falls back to raw extracted values, which may be incorrect. **Mitigation:** The preprocessing pipeline (grayscale, autocontrast, 3x upscale, sharpen) handles most common OCR issues, but very poor quality scans may still fail.

**Non-standard tax calculations:** The script assumes `total = subtotal + tax`. If an invoice has discounts, shipping charges, or other adjustments that break this relationship, the decimal recovery cross-check may select incorrect values or fail entirely. **Mitigation:** The fallback logic computes missing values when possible, but invoices with complex calculations may require manual review.

**Multiple tax rates:** If an invoice has multiple tax lines (e.g., "VAT 10%: 50.00" and "VAT 20%: 100.00"), the current regex captures only the first match. The script does not sum multiple tax lines. **Mitigation:** Future versions could extract all tax amounts and sum them, but this requires more complex parsing logic.

**Currency symbols and international formats:** The script handles basic comma/dot variations but may struggle with other formats (e.g., spaces as thousands separators, different decimal conventions in non-English locales like 1.234,56). **Mitigation:** The `decimal_variants()` function tries multiple decimal positions, which helps with some international formats, but comprehensive internationalization is not implemented.

**Very large batches:** The script processes documents sequentially. For batches with hundreds of documents, performance may be slow due to repeated OCR preprocessing. **Mitigation:** Consider parallelizing image OCR using multiprocessing or concurrent.futures for large batches.

**Structural marker false negatives:** If an invoice lacks all structural markers (no reference number, no date, no party identifier), it will be misclassified as `other`. This is rare in practice but possible for very simple or non-standard invoices. **Mitigation:** The scoring system provides a secondary check, but the structural prerequisite is a hard gate to prevent receipt/voucher misclassification.
