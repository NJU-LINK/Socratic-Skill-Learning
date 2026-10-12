---
name: financial-document-processor
description: >
  Process a mixed batch of financial and business documents (PDFs and images).
  Classify each as invoice or other based on content analysis, extract total and
  tax amounts from invoices, route files into output folders, and produce a
  summary CSV with per-invoice rows and a totals row.
---

# Financial Document Processor

## Overview

You have a directory of mixed business documents with opaque filenames. The task
is to:

1. Extract text from every PDF and JPG.
2. Classify each document as **invoice** or **other** using content cues only.
3. Move invoices to `/app/invoices/` and non-invoices to `/app/other/`.
4. Build `/app/invoices/summary.csv` with columns `filename,total_amount,vat_amount`,
   one row per invoice plus a final `total` row summing all invoices.
5. Leave the source directory empty.

---

## Step 1 — Environment Setup

```python
import os, shutil, csv, re, glob

SRC  = "/app/documents"
INV  = "/app/invoices"
OTH  = "/app/other"
CSV_PATH = os.path.join(INV, "summary.csv")

for d in (INV, OTH):
    os.makedirs(d, exist_ok=True)
```

Available tools (verify before use):
- **PDFs**: `pdftotext` (CLI), `fitz` (PyMuPDF), or `PyPDF2`/`pdfplumber`.
- **Images**: `pytesseract` + `PIL` for OCR.

---

## Step 2 — Text Extraction

### PDFs (text-based)

Use `pdftotext <file> -` via subprocess or `fitz.open(file)` page iteration.
If a page returns very little text but contains embedded images, treat it as an
image-based PDF and fall through to the image pipeline below.

```python
import subprocess
def extract_pdf_text(path):
    result = subprocess.run(["pdftotext", path, "-"],
                            capture_output=True, text=True)
    return result.stdout
```

### Images (JPG/PNG) and image-based PDF pages

Always **preprocess** before OCR to reduce noise:

1. Convert to grayscale.
2. Boost contrast (factor 2–3).
3. Sharpen.
4. Scale up 2–3× with LANCZOS.

```python
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

def ocr_image(path):
    img = Image.open(path)
    gray = ImageOps.grayscale(img)
    gray = ImageEnhance.Contrast(gray).enhance(2.5)
    gray = gray.filter(ImageFilter.SHARPEN)
    gray = gray.resize((gray.width * 2, gray.height * 2), Image.LANCZOS)
    return pytesseract.image_to_string(gray, config="--oem 3 --psm 6")
```

If the first OCR pass yields very little usable text, try PSM 3 or PSM 4, or
increase the scale factor to 3×. Multiple passes are acceptable.

---

## Step 3 — Document Classification

The filename is **not** informative. Classification must rely solely on
extracted text content. Use the decision rules below; combine signals when
no single cue is decisive.

### Invoice indicators (positive signals)

A document is likely an **invoice** when it combines a **payment request**
structure with a **tax/VAT/GST breakdown**. Look for:

| Signal | Examples |
|--------|----------|
| Document type label | "Invoice", "Tax Invoice", "Billing Statement", "Charge Note", "Remittance Notice" |
| Line-item structure | Service/product descriptions with amounts, then subtotal → tax → total |
| Payment request + tax | Any two of: a total-due amount, a tax/VAT/GST amount, and a reference/ID |
| Total-amount labels | "Grand Total", "Amount Due", "Payable Total", "Total Due", "Balance Due", "Total Payable", "Invoice Total" |
| Tax-amount labels | "VAT", "GST", "Tax", "Sales Tax", "Tax Amount", "VAT Amount", "Tax Included" (when paired with a total due) |

**Decisive rule**: If the document shows (a) a reference/document ID, (b) a
customer/client/bill-to party, (c) a line-item or service description with
amounts, and (d) a tax component, classify as **invoice** even if the word
"invoice" never appears.

### Non-invoice indicators (negative signals)

| Document type | Distinguishing cues |
|---------------|-------------------|
| **Receipt** | "Receipt", "Total Paid", "Card Payment Approved", "Payment Received" — confirms past payment rather than requesting future payment |
| **Purchase Order** | "Purchase Order", "PO Number", "Approval Status: Pending", "Requested Total", "Approved Spend" — a procurement request, not a billing document |
| **Payment Reminder** | "Payment Reminder", "Overdue Notice", explicitly says "This notice is not a tax invoice" — a follow-up, not the original invoice |
| **Expense Report** | "Expense Reimbursement", "Employee:", "Reclaimable Tax", "Approved Meals/Taxi/Travel" — internal reimbursement claim |
| **Quote / Estimate** | "Quote", "Estimate", "Proposal", "Valid Until" — not yet a billing document |
| **Contract / Agreement** | "Agreement", "Contract", "Terms and Conditions" with no itemized billing |

### Ambiguity resolution

When cues conflict or are sparse:

1. **Count positive vs negative signals** from the tables above.
2. A document that requests payment AND shows a tax breakdown is an invoice
   regardless of its title label.
3. A document that records a **completed** payment (receipt) or a **pending
   approval** (PO) is NOT an invoice even if it has totals and tax figures.
4. If the document explicitly states it is not an invoice (e.g., "This notice
   is not a tax invoice"), respect that statement → **other**.
5. Multi-page documents: cues may be spread across pages; aggregate before
   deciding.

---

## Step 4 — Financial Field Extraction (Invoices Only)

For each classified invoice, extract two fields:

### `total_amount`

The **final amount including tax**. Search for these labels (case-insensitive)
and take the monetary value on the same line or the next token:

```
Grand Total, Amount Due, Payable Total, Total Due, Balance Due,
Total Payable, Invoice Total, Total (including tax), Total Amount
```

**Fallback**: If no labeled total is found, look for the largest monetary
value on the page. Verify it is approximately equal to a subtotal + tax.

### `vat_amount`

The **tax/VAT/GST amount**. Search for these labels (case-insensitive):

```
VAT, GST, Sales Tax, Tax:, Tax Amount, VAT Amount, Tax Included
```

**Important**: Match `Tax` with a colon (`Tax:`) or as part of a compound
label (`Sales Tax`, `Tax Amount`) to avoid false positives from words like
"Taxi" in expense reports or "Taxt" in noisy OCR.

**Fallback**: If only a subtotal and total are visible, compute
`vat_amount = total_amount - subtotal`. If a tax rate and subtotal are
visible, compute `vat_amount = subtotal * rate`.

**Preference order**: Always prefer directly-labeled values over computed
ones. OCR can misread individual line items, so a labeled "Total Due" or
"GST" field is more reliable than arithmetic derivation.

### Parsing monetary values

Strip currency symbols, commas, and whitespace. Handle both `1,058.40` and
`1058.40`. Watch for OCR artifacts: `l` or `I` may replace `1`, `O` may
replace `0`, `S` may replace `5`.

```python
def parse_amount(raw):
    if raw is None:
        return 0.0
    cleaned = re.sub(r'[^\d.]', '', str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def extract_labeled_amount(text, label_pattern):
    """Extract the monetary value following a label on the same line.
    Example: 'Grand Total: 751.68' -> 751.68
    """
    m = re.search(
        rf'{label_pattern}[:\s]*[\$\u20ac\u00a3]?([\d,]+\.?\d*)',
        text, re.IGNORECASE
    )
    return parse_amount(m.group(1)) if m else 0.0

# Usage for total_amount:
total_labels = r'(?:grand\s*total|amount\s*due|payable\s*total|total\s*due|balance\s*due|invoice\s*total)'
total = extract_labeled_amount(text, total_labels)

# Usage for vat_amount:
vat_labels = r'(?:vat|gst|sales\s*tax|tax\s*amount|tax)'
vat = extract_labeled_amount(text, vat_labels)
```

When the OCR produces concatenated digits without a decimal (e.g., `105840`
for `1058.40`), check if the last two digits form a plausible cents value and
insert a decimal point accordingly. Cross-validate against other amounts on
the same document.

---

## Step 5 — File Routing

After classification:

```python
for fname, doc_class in classifications.items():
    src = os.path.join(SRC, fname)
    dst_dir = INV if doc_class == "invoice" else OTH
    shutil.move(src, os.path.join(dst_dir, fname))
```

Verify the source directory is empty after all moves.

---

## Step 6 — Summary CSV

Write `/app/invoices/summary.csv`:

```python
with open(CSV_PATH, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["filename", "total_amount", "vat_amount"])
    
    sum_total = 0.0
    sum_vat = 0.0
    for inv in sorted(invoice_data, key=lambda x: x["filename"]):
        writer.writerow([inv["filename"], f"{inv['total_amount']:.2f}", f"{inv['vat_amount']:.2f}"])
        sum_total += inv["total_amount"]
        sum_vat   += inv["vat_amount"]
    
    # Format all amounts to 2 decimal places for consistency
    writer.writerow(["total", f"{sum_total:.2f}", f"{sum_vat:.2f}"])
```

### Numeric formatting rules

- Write amounts as plain decimals with exactly 2 decimal places: `751.68`,
  `1408.00` (not `$751.68`, `751,68`, or `1408.0`).
- The `total` row sums must match the arithmetic sum of the invoice rows
  (within floating-point tolerance).

---

## Step 7 — Verification Checklist

Before finishing, confirm:

- [ ] `/app/documents/` is empty.
- [ ] Every original file exists in either `/app/invoices/` or `/app/other/`.
- [ ] `/app/invoices/summary.csv` exists with the correct header.
- [ ] The number of data rows (excluding header and total row) equals the
      number of files moved to `/app/invoices/` (excluding `summary.csv`).
- [ ] The `total` row sums match the column sums of the invoice rows.
- [ ] No non-invoice files appear in `/app/invoices/`.
- [ ] No invoice files appear in `/app/other/`.

---

## Handling Variation Across the Task Family

### Noisy OCR (document_modality_and_ocr_noise)
- Always preprocess images before OCR.
- Run multiple PSM modes if the first pass is poor.
- Use digit-whitelist OCR (`tessedit_char_whitelist=0123456789.,`) as a
  secondary pass to recover amounts when the full OCR garbles numbers.
- Cross-validate extracted numbers: `subtotal + tax ≈ total`.

### Weak invoice markers (document_content_patterns)
- Do not rely on the word "invoice" appearing in the text.
- Use the multi-signal decision rules in Step 3.
- Spread your search across the entire document text; classification cues
  may appear in different regions (header, body, footer).

### Varied financial expressions (financial_field_expression)
- Maintain a broad label dictionary for totals and tax amounts.
- When multiple amount candidates exist, prefer the one adjacent to a
  tax-inclusive label ("Amount Due", "Grand Total").
- If tax must be derived: `tax = total - subtotal` or `tax = subtotal × rate`.

### Batch scale (batch_scale_and_class_balance)
- The approach is identical regardless of batch size or class ratio.
- Process files in a loop; do not assume any fixed count or ratio.
- The CSV total row is always the sum of whatever invoices were found.
