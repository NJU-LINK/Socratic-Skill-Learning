---
name: financial-document-processor
description: >
  Process a mixed batch of financial and business documents (PDFs and images).
  Classify each as invoice or other based on content analysis, extract total and
  tax amounts from invoices, route files into output folders, and produce a
  summary CSV with per-invoice rows and a totals row.
---

# Financial Document Processor

## Critical Rule

**You MUST run the processing pipeline programmatically.** Do NOT manually
read document text and hardcode classifications or amounts into a script.
Every classification decision and every extracted number must come from
code that parses the document text at runtime. Copy the script below
into a single `task_shell` call and execute it.

## Complete Processing Script

```python
import os, shutil, csv, re, glob, subprocess
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# ── Paths ──────────────────────────────────────────────────────────────
SRC = "/app/documents"
INV = "/app/invoices"
OTH = "/app/other"
CSV_PATH = os.path.join(INV, "summary.csv")

for d in (INV, OTH):
    os.makedirs(d, exist_ok=True)

# ── 1. Text Extraction ────────────────────────────────────────────────

def extract_pdf_text(path):
    """Extract text from a text-layer PDF via pdftotext."""
    try:
        r = subprocess.run(["pdftotext", path, "-"],
                           capture_output=True, text=True, timeout=30)
        return r.stdout
    except Exception:
        return ""

def ocr_image(path):
    """OCR an image with preprocessing. Keeps best of PSM 6/4/3."""
    img = Image.open(path)
    gray = ImageOps.grayscale(img)
    gray = ImageEnhance.Contrast(gray).enhance(2.5)
    gray = gray.filter(ImageFilter.SHARPEN)
    gray = gray.resize((gray.width * 2, gray.height * 2), Image.LANCZOS)
    best = pytesseract.image_to_string(gray, config="--oem 3 --psm 6")
    for psm in ["4", "3"]:
        alt = pytesseract.image_to_string(gray, config=f"--oem 3 --psm {psm}")
        if len(alt.strip()) > len(best.strip()):
            best = alt
    return best

def extract_text(path):
    """Route to the right extractor; fall back to OCR for image-PDFs."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text = extract_pdf_text(path)
        if len(text.strip()) < 20:
            text = ocr_image(path)
        return text
    else:
        return ocr_image(path)

# ── 2. Classification (scoring system) ────────────────────────────────
# IMPORTANT: text is lowered before matching; every re.search also gets
# re.IGNORECASE as a safety net.
# OCR-tolerant design:
#   - Separators use [.:\-] because OCR confuses colon, period, and dash.
#   - Some keywords allow OCR variants (e.g. "nota" for "note").

POSITIVE_PATTERNS = [
    # Document-type labels (strong signal)
    (r'\binvoice\b', 3),
    (r'\bbilling\s*statement\b', 3),
    (r'\bcharge\s*not[eae]\b', 3),           # OCR: "nota" / "note"
    (r'\bremittance\s*notice\b', 3),
    (r'\btax\s*(?:document|invoice)\b', 3),
    # Payment-request totals
    (r'(?:grand\s*total|amount\s*due|payable\s*total|balance\s*due'
     r'|invoice\s*total|total\s*due|total\s*payable|net\s*total)', 2),
    # Tax components — all lowercase
    (r'\bvat\b', 1),
    (r'\bgst\b', 1),
    (r'\bsales\s*tax\b', 1),
    (r'\btax\s*amount\b', 1),
    (r'\btax\s*included\b', 1),
    # Reference / party structure — OCR-tolerant separators
    (r'(?:reference|ref|document\s*id|doc\s*r[ae]f)[.:\-\s]', 1),
    (r'(?:client|bill\s*to|customer|ship\s*to)[.:\-\s]', 1),
    # Line-item structure
    (r'(?:services?|retainer|order|freight|consulting|hardware)'
     r'[.:\-\s]*[\d,]+\.?\d*', 1),
]

NEGATIVE_PATTERNS = [
    (r'not\s*a\s*(?:tax\s*)?invoice', -100),
    (r'\breceipt\b', -3),
    (r'(?:total\s*paid|card\s*payment\s*approved|payment\s*received)', -3),
    (r'\bpurchase\s*order\b', -5),
    (r'\bpo\s*number\b', -3),
    (r'\bapproval\s*status\b', -3),
    (r'\brequested\s*total\b', -2),
    (r'\bapproved?\s*spend\b', -2),
    (r'\bexpense\s*reimbursement\b', -5),
    (r'\breclaimable\s*tax\b', -3),
    (r'\bemployee\s*[.:\-\s]', -2),
    (r'\bpayment\s*reminder\b', -3),
    (r'\boverdue\s*notice\b', -3),
    (r'\bquote\b', -2),
    (r'\bestimate\b', -2),
    (r'\bproposal\b', -2),
]

def classify(text):
    """Score the document; return 'invoice' if net score >= 3."""
    t = text.lower()
    score = 0
    for pattern, weight in POSITIVE_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            score += weight
    for pattern, weight in NEGATIVE_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            score += weight
    return "invoice" if score >= 3 else "other"

# ── 3. Amount Extraction ──────────────────────────────────────────────
# All separators use [.:\-] to handle OCR confusion between : . -

def parse_amount(raw):
    """Strip currency/comma noise, return float."""
    if raw is None:
        return 0.0
    cleaned = re.sub(r'[^\d.]', '', str(raw))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def find_labeled_amount(text, label_pattern):
    """Find LABEL <separator?> <currency?> <number>."""
    m = re.search(
        rf'{label_pattern}\s*[.:\-]?\s*'
        rf'(?:[\$\u20ac\u00a3\u00a5]?\s*)?'
        rf'([\d,]+\.?\d*)',
        text, re.IGNORECASE)
    return parse_amount(m.group(1)) if m else 0.0

def find_vat_amount(text):
    """Extract VAT/GST/tax amount, skipping rate percentages."""
    # Try 1: VAT/GST, skip past "10%" rate patterns
    m = re.search(
        r'(?:vat|gst)\s*(?:\d+\s*%?\s*)?[.:\-]\s*'
        r'(?:[\$\u20ac\u00a3\u00a5]?\s*)?([\d,]+\.?\d*)',
        text, re.IGNORECASE)
    if m:
        return parse_amount(m.group(1))
    # Try 2: other tax labels
    m = re.search(
        r'(?:sales\s*tax|tax\s*amount|tax\s*included|(?:^|\n)\s*tax)'
        r'\s*[.:\-]?\s*'
        r'(?:[\$\u20ac\u00a3\u00a5]?\s*)?([\d,]+\.?\d*)',
        text, re.IGNORECASE)
    if m:
        return parse_amount(m.group(1))
    return 0.0

TOTAL_LABELS = (
    r'(?:grand\s*total|amount\s*due|payable\s*total|total\s*due'
    r'|balance\s*due|total\s*payable|invoice\s*total'
    r'|total\s*amount|net\s*total)'
)

def extract_amounts(text):
    """Return (total_amount, vat_amount)."""
    total = find_labeled_amount(text, TOTAL_LABELS)
    vat   = find_vat_amount(text)

    # Fallback: largest N.NN value on page
    if total == 0.0:
        amounts = [parse_amount(m) for m in
                   re.findall(r'[\d,]+\.\d{2}', text)]
        if amounts:
            total = max(amounts)

    # Fallback: derive VAT = total - subtotal
    if vat == 0.0 and total > 0:
        sm = re.search(
            r'(?:subtotal|sub\s*total|net\s*charges?)[.:\-]?\s*'
            r'(?:[\$\u20ac\u00a3\u00a5]?\s*)?([\d,]+\.?\d*)',
            text, re.IGNORECASE)
        if sm:
            sub = parse_amount(sm.group(1))
            if 0 < sub < total:
                vat = round(total - sub, 2)

    return total, vat

# ── 4. Process All Documents ──────────────────────────────────────────

files = sorted(
    glob.glob(os.path.join(SRC, "*.pdf")) +
    glob.glob(os.path.join(SRC, "*.jpg")) +
    glob.glob(os.path.join(SRC, "*.jpeg")) +
    glob.glob(os.path.join(SRC, "*.png"))
)

invoice_rows = []

for fpath in files:
    fname = os.path.basename(fpath)
    text  = extract_text(fpath)
    cls   = classify(text)

    if cls == "invoice":
        total, vat = extract_amounts(text)
        invoice_rows.append({
            "filename": fname,
            "total_amount": total,
            "vat_amount": vat,
        })
        print(f"[INVOICE] {fname}  total={total}  vat={vat}")
    else:
        print(f"[OTHER]   {fname}")

    dst_dir = INV if cls == "invoice" else OTH
    shutil.move(fpath, os.path.join(dst_dir, fname))

# ── 5. Write Summary CSV ──────────────────────────────────────────────

invoice_rows.sort(key=lambda r: r["filename"])

with open(CSV_PATH, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["filename", "total_amount", "vat_amount"])
    sum_total = 0.0
    sum_vat   = 0.0
    for row in invoice_rows:
        writer.writerow([
            row["filename"],
            f"{row['total_amount']:.2f}",
            f"{row['vat_amount']:.2f}",
        ])
        sum_total += row["total_amount"]
        sum_vat   += row["vat_amount"]
    writer.writerow(["total", f"{sum_total:.2f}", f"{sum_vat:.2f}"])

print(f"\nCSV: {CSV_PATH}")
with open(CSV_PATH) as f:
    print(f.read())

# ── 6. Verification ──────────────────────────────────────────────────

remaining = os.listdir(SRC)
inv_files = [f for f in os.listdir(INV) if f != "summary.csv"]
oth_files = os.listdir(OTH)

print(f"documents remaining: {len(remaining)} (expect 0)")
print(f"invoices: {len(inv_files)},  other: {len(oth_files)}")
assert len(remaining) == 0, "documents not drained!"
assert len(inv_files) == len(invoice_rows), "invoice count mismatch!"
assert len(inv_files) + len(oth_files) == len(files), "file count!"
print("OK — all checks passed")
```

## How It Works

### Text extraction
- **PDFs**: `pdftotext` for text-layer PDFs; auto-falls-back to OCR for
  image-based PDFs (< 20 chars).
- **Images**: `pytesseract` with preprocessing (grayscale → 2.5× contrast →
  sharpen → 2× LANCZOS). Keeps best of PSM 6/4/3.

### Classification
- Weighted scoring: positive patterns add, negative patterns subtract.
- Invoice if net score ≥ 3.
- OCR-tolerant: separators accept `.`, `:`, `-`; keywords allow common OCR
  variants (`nota`/`note`, `raf`/`ref`).
- `"not a tax invoice"` triggers −100 override.

### Amount extraction
- **total_amount**: labeled totals (Grand Total, Amount Due, Payable Total,
  Total Due, etc.). Fallback: largest `N.NN` on page.
- **vat_amount**: tries VAT/GST (skipping rate % like "VAT 10%:"), then other
  tax labels. Fallback: `total − subtotal`.
- All separators use `[.:\-]` for OCR robustness.

### Output
- Files moved to `/app/invoices/` or `/app/other/`.
- CSV amounts formatted to exactly 2 decimal places.

## Adaptation Notes

- **Noisier OCR**: Add digit-whitelist pass
  (`--tessedit_char_whitelist=0123456789.,`) if amounts are garbled.
- **European formats** (`1.058,40`): Swap `.`/`,` roles in `parse_amount`.
- **Multi-page PDFs**: `pdftotext` concatenates pages automatically.
- **New document types**: Add to POSITIVE_PATTERNS / NEGATIVE_PATTERNS.
  The ≥ 3 threshold prevents single-signal false positives.
- **Large batches**: Loop covers all PDF/JPG/JPEG/PNG — no code change.
