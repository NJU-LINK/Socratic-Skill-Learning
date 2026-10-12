---
name: financial-document-processor
description: Process mixed batches of financial documents (PDFs and images) by classifying them as invoices or other document types, extracting financial fields from invoices using arithmetic consistency validation, and organizing files into appropriate directories with summary reports.
---

# Financial Document Processor

## Overview

Process mixed batches of business documents (PDFs and images) to:
1. Classify each document as `invoice` or `other` based on content
2. Extract financial fields (`total_amount`, `vat_amount`) from invoices
3. Move invoices to `/app/invoices/` and non-invoices to `/app/other/`
4. Generate a summary CSV with extracted fields and totals

## Core Insight

**The invoice is an arithmetic system, not a collection of independent fields.**

Instead of parsing each field independently and hoping for the right number, extract ALL monetary amounts from the document, use line context to label their roles, then validate with arithmetic constraints: `total ≈ subtotal + tax`.

## Classification Strategy

### Business Purpose Distinction

Before classifying any document as an invoice, ask: **"Is this document *requesting* payment, or *confirming* payment already made?"**

- **Invoice**: Requests future payment (billing document from seller to buyer)
- **Receipt**: Confirms payment already made (proof of completed transaction)
- **Payment confirmation/remittance advice**: Sent by payer to confirm they've paid

### Use Both Positive and Negative Signals

**Negative signals (disqualify from invoice):**
- Purchase Order (requests goods/services, not payment)
- Payment Reminder (references existing debt, not a new invoice)
- Expense Reimbursement / Reimbursement Summary (internal claim, not seller billing)
- "Not a tax invoice" / "Not an invoice" (explicit disqualification)
- Delivery Note, Packing Slip (logistics documents)
- **Receipt** (proof of payment already made, not a billing request)
- "Card Payment", "Payment Approved" (indicates completed transaction)

**Positive signals (indicate invoice — requesting payment):**
- Invoice, Tax Document, Tax Invoice
- Billing Statement, Charge Note
- Remittance Notice (when it contains "Payable Total", "Ship To" — seller requesting payment)
- Amount Due, Total Due, Payable

**Fallback structural cues:**
- Customer/Bill To + Total Due/Payable + Tax/VAT keywords

Use fuzzy matching (max_distance=2-3) to handle OCR errors in keywords.

## Extraction Strategy

### Phase 1: Line-Label-First (Three-Tier Keyword Matching)

For each line in the document:
1. Extract all monetary amounts
2. Filter out non-field numbers:
   - Skip lines with date/reference/ID keywords
   - Skip integers > 4 digits (likely reference numbers)
   - Filter out percentages (numbers followed by %)
3. Label the line's role using **three-tier keyword matching**:

**Tier 1: Word-boundary regex for short keywords (3-4 chars)**
- Use `\btax\b`, `\bvat\b`, `\bgst\b` to prevent false positives inside words
- **Critical pitfall**: Fuzzy matching with distance 1 for 3-char keywords causes false matches: "retainer" matches "tax" (via "tai"), "subtotal" matches "tax" (via "tal"), "freight" matches "gst" (via "ght")

**Tier 2: Substring/fuzzy matching for longer phrases**
- Multi-word keywords like `sales tax`, `total due`, `payable total` are long enough to avoid false positives
- Use substring or fuzzy matching (max_distance=2) for these

**Tier 3: Explicit OCR-variant patterns as safety net**
- `^\s*ast\s*\d` for "ast78.40" → tax (VAT with V dropped)
- `teal\s+due` for "Teal Due: 1058.40" → total (Total with o→e)
- `charge\s+not[eo]` for "Charge Nate"/"Charge Nols" → classification

**Line role labels:**
- **Subtotal**: subtotal, net charges, service line items (Consulting Services, Design Retainer, Freight Services, Hardware Order, etc.)
- **Tax/VAT**: vat, tax, gst, sales tax (but NOT document headers like "Tax Document")
- **Total**: total, amount due, grand total, payable total, total paid

**Key design choices:**
- Subtotal detection uses service-line keywords, not just "subtotal" — many invoices don't say "subtotal" explicitly
- Tax lines exclude document-type headers — "Tax Document" is skipped because it contains "document"
- For lines with multiple numbers (e.g., "VAT 10%: 128.00"), take the largest non-percentage number
- OCR-variant patterns ensure tax lines are labeled even when keywords are mangled

### Phase 2: Arithmetic Validation

Use arithmetic consistency to select among candidates:

1. **Try all combinations** of (total, subtotal, tax) candidates
2. **Score each combination** by arithmetic fit: `score = |implied_tax - closest_tax_candidate|`
3. **Select the combination with lowest score** (best arithmetic fit)
4. **Handle OCR decimal-point loss**: For integer candidates > 100, try dividing by 100 and check if the repaired version gives better arithmetic fit

**Example:**
- Receipt with OCR noise: candidates are [49.27, 48.27, 483, 489, 469, 5420, 6420]
- After decimal repair: [49.27, 48.27, 4.83, 4.89, 4.69, 54.20, 64.20]
- Check: 49.27 + 4.93 ≈ 54.20 → pick total=54.20, subtotal=49.27, tax=4.93

## OCR Handling

### For Images (JPG, PNG, etc.)

Use Tesseract with multiple PSM modes (3, 4, 6, 11, 12) to maximize keyword coverage:
- Combine results from all modes
- Deduplicate lines
- Use the combined text for classification and extraction

**Common OCR errors to handle:**
- Decimal point loss: `5420` → `54.20`, `7840` → `78.40`
- Keyword misspellings: "Subtoat" → "subtotal", "otal Paid" → "total paid", "Charge Nate" → "Charge Note"
- Use fuzzy matching (max_distance=1-2) for keyword detection

### For PDFs

Use PyMuPDF (fitz) for text extraction, fallback to pdftotext if needed.

## Implementation Checklist

1. **Extract text** from each document (PDF or image)
2. **Classify** as invoice or other using positive/negative signals
3. **For invoices:**
   - Extract all monetary amounts with line context
   - Filter out non-field numbers (dates, refs, percentages)
   - Label each line's role (subtotal/tax/total) using keywords
   - Use arithmetic consistency to select best candidates
   - Handle OCR decimal-point loss
4. **Move files** to appropriate directories
5. **Generate summary.csv** with columns: filename, total_amount, vat_amount
6. **Add total row** with sums of all invoice amounts
7. **Verify** documents directory is empty after processing

## Family Variations

This skill handles variation along these dimensions:

### Document Content Patterns
- Invoices with weaker/less standard markers
- Non-invoices with overlapping financial vocabulary
- Classification cues spread across multiple text regions

### Document Modality and OCR Noise
- Scans with noisier OCR output
- PDFs with mixed embedded text and rendered pages
- Different page layouts or image quality
- Partially legible fields that must be inferred

### Financial Field Expression
- Amounts in different numeric conventions (European vs standard)
- Taxes recovered from subtotals, rates, or line-item summaries
- Multiple plausible amount candidates requiring arithmetic validation

### Batch Scale and Class Balance
- Small or large batches
- Invoice-heavy or other-heavy mixes
- Summary row correctness across varying invoice counts

## Debugging Tips

**If classification is wrong:**
- Check for negative signals that should disqualify the document
- Verify fuzzy matching is catching OCR-misspelled keywords
- Ensure document-type headers aren't triggering false positives
- Remember: receipts confirm payment, they don't request it

**If extraction is wrong:**
- Print line labels to see which lines are being classified as subtotal/tax/total
- Check if percentages are being filtered correctly
- Verify arithmetic consistency scoring is selecting the right combination
- For OCR noise, check if decimal repair is being applied correctly

**Common pitfalls:**
- Taking the first number on a line when there are multiple (e.g., "VAT 10%: 128.00" — take 128, not 10)
- Not filtering out document-type headers from tax classification
- Applying decimal repair too aggressively (only repair when arithmetic fit improves)
- Not handling the case where subtotal is labeled by service-line keywords rather than "subtotal"
- Misclassifying receipts as invoices (check for "Card Payment", "Paid", "Receipt" keywords)
