---
name: financial-document-processor
description: >-
  Process a mixed batch of financial documents (PDF and image): classify each as
  invoice or other based on content, extract total_amount and vat_amount from
  invoices, move files into output folders, and produce a summary CSV with a
  totals row.  Handles OCR noise, varied label conventions, and non-invoice
  documents that share financial vocabulary.
---

# Financial Document Processor

## 0  Quick Start — Run the Reference Script

```bash
/opt/financial-doc-venv/bin/python3 /skill/scripts/process_documents.py
```

This single command processes all documents in `/app/documents/`, classifies
them, extracts amounts, moves files, and writes the summary CSV.  No manual
steps needed.  All tools (`pdftotext`, `tesseract`, `convert`) are pre-installed.

---

## 1  Task Overview

Given a directory of PDFs and/or JPGs with opaque filenames:

1. Extract readable text from every document.
2. Classify each document as **invoice** or **other** using content signals.
3. Move invoices to `/app/invoices/`, everything else to `/app/other/`.
4. For every invoice, extract `total_amount` (final amount including tax) and
   `vat_amount` (the VAT / tax line).
5. Write `/app/invoices/summary.csv` with columns `filename,total_amount,vat_amount`,
   one row per invoice, plus a final `total` row with column sums.
6. Leave `/app/documents/` empty.

---

## 2  Text Extraction

### PDFs — embedded text
```
pdftotext -layout <file> -
```
If the output is empty or very short (< 20 chars), the PDF is likely a scan;
fall back to image-based OCR by converting pages with `pdftoppm`.

### Images (JPG / PNG / TIFF) — OCR
Raw tesseract on receipt-quality scans often drops decimals or garbles keywords.
**Always preprocess** before OCR:

| Config | Command | Use |
|--------|---------|-----|
| A | `convert <in> -resize 200% -sharpen 0x1 /tmp/a.jpg` → `tesseract /tmp/a.jpg stdout --psm 6` | General — best all-round |
| B | `convert <in> -resize 250% -sharpen 0x2 /tmp/b.jpg` → `tesseract /tmp/b.jpg stdout --psm 6` | Receipts with small print |
| C | `convert <in> -resize 200% -contrast -sharpen 0x1 /tmp/c.jpg` → `tesseract /tmp/c.jpg stdout --psm 6` | Low-contrast scans |

Run **all three configs** and keep every resulting text.  Amount extraction
(§4) uses arithmetic verification to pick the best result automatically.

PSM 6 (single uniform block) works well for invoices and receipts.  PSM 4
(single column) is a useful fallback for columnar layouts.

---

## 3  Classification — Invoice vs Other

### Core concept

**An invoice is a billing document that requests payment.**  Receipts (proof of
payment already made), expense claims, purchase orders, and collection notices
are **not** invoices, even though they may contain financial vocabulary like
"VAT", "total", or "tax".

### Score-based classifier

Start at score 0; add positive weights, subtract negative weights.
**Threshold: score ≥ 3 → invoice, else other.**

### Positive signals (billing / invoicing documents)

| Signal | Weight | Rationale |
|--------|--------|-----------|
| `\binvoice\b` | +4 | Direct label |
| `\bbilling\s*statement\b` | +3 | Billing document |
| `\bcharge\s*not[ea]\b` | +3 | Charge note = billing |
| `\bremittance\b` | +2 | Remittance advice accompanies invoice |
| `\btax\s*document\b` | +2 | Tax-related billing |
| `(grand\|payable\|net)\s*total` | +2 | Completed-transaction total |
| `total\s*(due\|net\|payable)` | +2 | Amount owed (future) |
| `amount\s*(due\|payable)` | +2 | Amount owed on a billing |
| `(vat\|gst\|sales.tax)\b.*\d` | +1 | Tax breakdown present |
| `\btax\b.*\d` (not in title) | +1 | Tax line with amount |

### Negative signals (NOT invoices)

| Signal | Weight | Rationale |
|--------|--------|-----------|
| `\breceipt\b` or `recei[gpct]` | **−3** | **Receipt = proof of payment, not a bill** |
| `card\s*payment` | **−2** | POS payment confirmation language |
| `total\s*pai[de]?\b` | **−1** | Past-tense "paid" = already settled |
| `not\s*(a\s*)?(tax\s*)?invoice` | −6 | Explicit disclaimer |
| `purchase\s*order` | −4 | Pre-transaction, not a bill |
| `payment\s*reminder` | −4 | Collection notice, not an invoice |
| `expense\s*reimbursement` | −4 | Internal claim, not a bill |
| `approval\s*status` | −3 | Document pending, not final |
| `reclaimable\s*tax` | −3 | Internal expense claim |
| `\bpending\b` | −2 | Not yet issued |
| `estimated\s*tax` | −2 | Not a final charge |
| `requested\s*total` | −2 | Pre-transaction ask |
| `spend\s*ceiling` | −2 | Budget limit, not a bill |
| `outstanding\s*balance` | −2 | Collection context |

### Decision rules derived from evidence

- A **Receipt** with "Card Payment Approved" and "Total Paid" is always
  **other**: `receipt (−3) + card payment (−2) + total paid (−1) + vat (+1) = −5`.
- A "Payment Reminder" saying *"not a tax invoice"* is always **other**
  (combined −6 − 4 − 2 = −12).
- A "Purchase Order" with "Approval Status: Pending" is always **other**
  (−4 − 3 − 2 − 2 = −11).
- An "Expense Reimbursement Summary" with "Reclaimable Tax: 0.00" is always
  **other** (−4 − 3 = −7).
- A "Remittance Notice" with "Sales Tax" and "Payable Total" is an **invoice**
  (+2 + 2 + 1 + 1 = +6).
- A "Charge Note" with "GST" and "Total Due" is an **invoice**
  (+3 + 2 + 1 = +6).

### OCR tolerance

Strip leading punctuation (`'`, `(`) and apply case-insensitive matching.
Words like `Receict`, `Receigt`, `Receige` all contain `recei` → the pattern
`recei[gpct]*\b` catches them.

---

## 4  Amount Extraction

### 4.1  Identify total, tax, and subtotal lines

Use **per-line** keyword matching (case-insensitive, after stripping OCR
artifacts from line starts):

**Total lines** — include if line matches:
- `(grand|payable|net)\s*total`
- `total\s*(due|net|payable|paid|pai|pat)`
- `amount\s*(due|payable)`
- OCR-tolerant: `\bto[ta]a?l?\b.*\d` (catches "Toal Due", "Total Pai", "Total Pat")

**Exclude** from totals: lines starting with `sub` that contain a digit (subtotals).

**Tax/VAT lines** — include if line matches:
- `\bvat\b.*\d`, `\bgst\b.*\d`
- `sales\s*tax.*\d`
- `\btax\b.*\d` but **not** `tax\s*(document|ref|id|number)` and **not**
  lines containing `estimated|prior|reclaimable|approx`

**Subtotal lines** — include if line starts with `sub` and contains a digit
(catches "Subtotal", "Sublotat", "Subtoat", "Subtotat"), or matches
`net\s*charges` with a digit.

### 4.2  Parse numbers

1. Match number tokens: `[\d,]+(?:\.\d+)*`
2. **European format detection**: If the raw string has both dots and a
   comma, and the comma is followed by 1–2 digits at the end (e.g.
   `1.058,40`), treat dots as thousands separators and the comma as
   decimal → `1058.40`.
3. Otherwise strip commas (US): `1,058.40 → 1058.40`
4. Multiple dots → keep only last decimal: `1.058.40 → 1058.40`
5. Skip percentages: if token is immediately followed by `%`, ignore it
   (handles "VAT 10%: 128.00" — 10 is the rate, 128.00 is the amount).

### 4.3  Fix missing decimals (OCR artefact)

Scanned receipts often drop the decimal point:
- `"5420"` should be `54.20`
- `"483"` should be `4.83` (or `4.93` — depends on OCR run)
- `"7840"` should be `78.40`

**Rule:** If the **raw string** of a number from a total or tax line contains
no decimal point and the parsed value is an integer ≥ 100, divide by 100.
Checking the raw string (not the float) prevents false positives on values
like `1,408.00` which parse to `1408.0` (a float equal to its int cast).

### 4.4  Multi-config verification (images only)

For each OCR config text, independently extract:
- `total_cands` — all plausible total values (raw + decimal-fixed)
- `vat_cands` — all plausible tax values (raw + decimal-fixed)
- `subtotal` — best subtotal candidate

Score every `(total, vat)` pair:

```
if subtotal is known:
    error = |total − subtotal − vat|
else:
    error = 0   (cannot verify; accept pair)
```

Pick the pair with the **lowest error** across all configs.  This selects the
OCR run whose arithmetic is most self-consistent.

### 4.5  Rate-based tax calculation

When a tax line contains a percentage rate (e.g. "VAT 10%", "GST @ 8.5%")
but **no explicit monetary amount**, and a subtotal is known:

```
computed_vat = subtotal × rate / 100
```

Accept the computed VAT if `|total − subtotal − computed_vat| < 1.0`.
This handles documents that express tax as a rate rather than an amount.

### 4.6  Arithmetic fallback

When keyword-based extraction finds a total but **no** tax line (common when
OCR garbles the tax keyword, e.g. `ast 7840` for `Tax 78.40`):

1. Collect every number on the page.
2. For each number N (and its decimal-fixed variant), check whether
   `total − N` equals another number on the page (within 0.02).
3. If found: `vat = N`, `subtotal = total − N`.

Also handle the case where only total and subtotal are found:
`vat = total − subtotal`.

### 4.7  Aggressive subtotal search

When no explicit subtotal line exists, look for the **largest monetary amount
that is neither the total nor the tax** and is between 30 % and 100 % of the
total.  Use it as the inferred subtotal for arithmetic verification.

**Guard against false positives:**
- Skip lines matching date/reference patterns (`date:`, `issued:`, `ref:`,
  `reference:`, `po:`, `document id:`, etc.)
- Skip integer values in the year range 1900–2100
- These filters prevent dates (e.g. "2026-01-20") and reference numbers
  (e.g. "BH-10021") from being misidentified as subtotals.

---

## 5  Output

### Per-document error handling
Each document is processed inside a try/except block. If extraction or
classification raises an exception, the error is logged and the document
is moved to `/app/other/` as a safe default. This prevents a single
malformed document from stalling the entire batch.

### File moves
- `shutil.move(doc, /app/invoices/<name>)` for invoices
- `shutil.move(doc, /app/other/<name>)` for non-invoices
- Confirm `/app/documents/` is empty when done.

### summary.csv
```
filename,total_amount,vat_amount
<inv1>.pdf,751.68,55.68
<inv2>.jpg,1058.40,78.40
...
total,<sum_total>,<sum_vat>
```

- Two decimal places for all amounts (`f"{val:.2f}"`).
- The `total` row is the **last** row.
- Non-invoice documents are **not** included.

---

## 6  Verification Checklist

After processing, verify:

- [ ] `/app/documents/` is empty.
- [ ] `/app/invoices/` contains only invoice files + `summary.csv`.
- [ ] `/app/other/` contains only non-invoice files.
- [ ] `summary.csv` header is exactly `filename,total_amount,vat_amount`.
- [ ] Number of data rows equals number of invoice files.
- [ ] The `total` row sums match column sums.
- [ ] For each invoice: `total_amount > vat_amount > 0`.
- [ ] For each invoice with a found subtotal: `subtotal + vat ≈ total` (±0.50).

---

## 7  Variation Axes Coverage

| Axis | Strategy |
|------|----------|
| **document_content_patterns** | Score-based classification distinguishes billing documents from receipts, internal claims, and pre-transaction documents. Negative signals reject look-alikes that share financial vocabulary. |
| **document_modality_and_ocr_noise** | Multi-config preprocessing + arithmetic verification handles noisy scans, mixed PDFs, and partial legibility. Per-document error handling prevents one bad document from stalling the batch. |
| **financial_field_expression** | Flexible line predicates + decimal fixing (US and European formats) + rate-based tax calculation + arithmetic fallback covers varied labels, numeric conventions, rate-only tax expressions, and missing explicit fields. Date/reference filtering in subtotal inference prevents false matches. |
| **batch_scale_and_class_balance** | Per-document processing loop is batch-size agnostic; CSV totals row auto-adjusts. |

---

## 8  Reference Script

See `scripts/process_documents.py` for a complete, executable implementation.
**Run it directly:**

```bash
/opt/financial-doc-venv/bin/python3 /skill/scripts/process_documents.py
```

It requires only system tools (`pdftotext`, `tesseract`, `convert`) and the
Python standard library — no additional packages.
