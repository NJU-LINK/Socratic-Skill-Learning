---
name: financial-document-processor
description: >
  Classify mixed financial documents (invoices vs. non-invoices) from opaque
  filenames, extract total_amount and vat_amount from invoices, route files to
  output directories, and produce a summary.csv with a totals row. Handles
  PDFs and JPGs/PNGs with OCR noise, multi-signal classification with
  disclaimer vetoes, and diverse financial field labels.
---

# Financial Document Processor

## Overview

Process a batch of mixed financial documents from a source directory:
1. Extract text from PDFs (pdftotext) and images (tesseract OCR)
2. Classify each document as `invoice` or `other`
3. Extract `total_amount` and `vat_amount` from invoices
4. Move files to `/app/invoices/` or `/app/other/`
5. Write `/app/invoices/summary.csv` with per-invoice rows and a `total` row

## Architecture

Four independent stages: **Extract → Classify → Extract Fields → Route & Summarize**

## Stage 1: Text Extraction

### PDFs
Use `pdftotext <file> -` to extract embedded text.

### Images (JPG/PNG)
Use `tesseract <file> stdout` with multiple PSM modes (3, 4, 6, 11).
**Do NOT pick a single PSM text for field extraction** — no single PSM mode
reliably produces all correct values. Instead:

1. Extract text from ALL PSM modes
2. For each field (subtotal, vat, total), collect candidate amounts from ALL
   PSM texts using label-aware extraction
3. Use consistency-based merging: find the combination where
   `subtotal + vat ≈ total` with the best score
4. Scoring considers: consistency error, PSM frequency (values appearing in
   more modes are more reliable), explicit-vs-inferred VAT, and tax rate
   plausibility (penalize >20% rates)

If raw OCR is sparse (<30 chars across all modes), preprocess with
ImageMagick: resize 200%, sharpen, threshold, then re-OCR.

### OCR Noise Handling
- Apply character substitution ONLY to amount-value regions (not classification text):
  O→0, o→0, I→1, l→1, |→1, S→5, s→5, B→8, Z→2, z→2
- Use fuzzy label matching: strip non-alpha, lowercase, check key substrings
- Try multiple tesseract PSM modes and merge results

## Stage 2: Classification (Multi-Signal Scoring)

### CRITICAL: Check disclaimers FIRST (immediate veto)
Patterns: `not an invoice`, `not a tax invoice`, `this notice is not`, `not a bill`

### Negative document types (immediate veto)
`purchase order`, `expense reimbursement`, `payment reminder`, `credit memo`,
`statement of account`, `remittance advice` (when paired with non-invoice context)

### Positive signals (accumulate score)
| Signal | Weight |
|--------|--------|
| "invoice" or "tax invoice" as document title | +2 |
| "charge note", "billing statement" as title | +2 |
| "Bill To", "Ship To", "Sold To" + named party | +1 |
| "Customer:" or "Client:" with named entity | +1 |
| "Grand Total", "Amount Due", "Total Due", "Payable Total" | +1 |
| Tax line with amount: "VAT:", "Tax:", "GST:" + numeric value | +1 |
| Line-item + total structure | +1 |
| Receipt with subtotal + tax + total structure | +1 |

### Negative signals (reduce score)
| Signal | Weight |
|--------|--------|
| "Employee:", "Approval Status:", "Reimbursement" | -2 |
| "Estimated Tax", "Prior Tax", "Requested Total" | -1 |
| "Pending", "Approved Spend Ceiling" | -1 |

### Decision rule
- Score ≥ 2 → invoice
- Score < 2 → other

## Stage 3: Field Extraction

### total_amount (final amount including tax)
**Positive labels:** grand total, total due, amount due, payable total,
invoice total, balance due, total amount, total paid, net total, amount payable

**Exclusion labels:** subtotal, sub-total, requested, estimated,
approved spend, outstanding, prior

**Tie-breaking:** Take the LARGEST valid amount among candidates (final total
is always ≥ any sub-component).

### vat_amount (tax/VAT/GST amount)
**Positive labels:** vat included, vat amount, vat, tax amount, tax included,
sales tax, gst, tax

**Exclusion labels:** estimated, prior, reclaimable, reclamation

**Rate vs. amount:** If label includes a percentage ("VAT 10%: 128.00"),
extract the numeric amount after the colon, not the rate.

### Numeric parsing
1. Strip currency symbols ($, €, £, USD, EUR)
2. Remove thousands separators (commas)
3. Apply OCR character cleanup on the number string
4. Parse as float, round to 2 decimal places

## Stage 4: Routing & Summary

1. Create `/app/invoices/` and `/app/other/` directories
2. Move each file to the appropriate directory
3. Write `summary.csv` with columns: `filename`, `total_amount`, `vat_amount`
4. One row per invoice, then a final row with `filename=total` and summed amounts
5. Verify `/app/documents/` is empty after processing

## Robustness Principles

1. **Disclaimers are absolute vetoes** — override all positive signals
2. **Classification uses accumulated evidence** — no single keyword decides
3. **OCR cleanup is scoped** — character substitution only near amount fields
4. **Amount extraction separates positive from exclusion labels**
5. **Tie-break by magnitude** — final total is always the largest amount
6. **Preprocess images only when raw OCR is sparse**
7. **Multiple OCR modes** — merge results from different tesseract PSM modes
