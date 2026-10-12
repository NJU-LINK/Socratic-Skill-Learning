# Implementation Notes for v01

## Task Completion Status

✅ **All requirements met:**
- 8 documents processed (4 invoices, 4 non-invoices)
- Files moved to correct directories
- summary.csv generated with correct amounts
- Documents directory emptied

## Classification Results

**Invoices (4):**
1. `28dc9c7b312111cf.jpg` - Receipt (OCR noise handled via arithmetic cross-check)
2. `64c27dc50e7eedf2.pdf` - Tax Document (functional classification: requests payment)
3. `72ac345a94c7bfcd.pdf` - Billing Statement
4. `eb21ac77b4a28377.jpg` - Charge Note (OCR noise handled)

**Other (4):**
1. `3a9e2445a266b33d.jpg` - Expense Reimbursement (employee→employer)
2. `a5d044b90b7cd011.pdf` - Remittance Notice (buyer→seller: "Dispatch Date" = payment being sent)
3. `d06591e5449a36dc.pdf` - Payment Reminder (explicit disclaimer: "not a tax invoice")
4. `e551230b838b3fe1.pdf` - Purchase Order (approval status: pending)

## Financial Amounts Extracted

| Invoice | Total Amount | VAT Amount |
|---------|--------------|------------|
| 28dc9c7b312111cf.jpg | 54.20 | 4.93 |
| 64c27dc50e7eedf2.pdf | 751.68 | 55.68 |
| 72ac345a94c7bfcd.pdf | 1408.00 | 128.00 |
| eb21ac77b4a28377.jpg | 1058.40 | 78.40 |
| **Total** | **3272.28** | **267.01** |

## Key Challenges Solved

### 1. OCR Noise on Receipt (28dc9c7b312111cf.jpg)
- **Problem**: OCR read "VAT Included 493" instead of "4.93" (decimal point dropped)
- **Solution**: Arithmetic cross-validation: subtotal (49.27) + VAT (4.93) = total (54.20) ✓
- **Mechanism**: When extracted values don't satisfy `subtotal + tax ≈ total`, recompute from the relationship

### 2. OCR Noise on Charge Note (eb21ac77b4a28377.jpg)
- **Problem**: OCR read "GST. 78.40" with period separator instead of colon
- **Solution**: Flexible separator pattern `[\s:.]*` accepts colon, period, space, or nothing

### 3. Tax Document Classification (64c27dc50e7eedf2.pdf)
- **Problem**: Title says "Tax Document" but functionally requests payment
- **Solution**: Functional classification principle - classify by what document DOES, not by title
- **Signals**: "Grand Total", "Please remit" = seller→buyer requesting payment = invoice

### 4. Remittance Notice Directionality (a5d044b90b7cd011.pdf)
- **Problem**: Has "Ship To" and "Payable Total" which look like seller→buyer signals
- **Solution**: Check action verb - "Dispatch Date" + "Remittance" = buyer dispatching payment = buyer→seller = other
- **Key insight**: "Ship To" describes the original order, not the document's direction

## Spec Variation Coverage

The SKILL.md addresses all four spec dimensions:

1. **document_content_patterns**: Functional classification + directionality checking handles weak markers, overlapping vocabulary, and distributed cues

2. **document_modality_and_ocr_noise**: Multi-PSM OCR + arithmetic cross-validation handles noisy scans, mixed PDFs, and partial legibility

3. **financial_field_expression**: Flexible regex + arithmetic inference handles different numeric conventions, implicit taxes, and multiple candidates

4. **batch_scale_and_class_balance**: Dynamic processing handles any batch size and class mix

## Lessons Learned

1. **Don't rely on document type labels as proxies** - always check functional direction
2. **Arithmetic relationships are powerful validation signals** for noisy OCR
3. **Action verbs are decisive** for ambiguous document types (remittance, purchase order)
4. **Multi-PSM OCR selection by arithmetic consistency** beats longest-text heuristic
5. **Flexible regex patterns** (`sub\w+`, `[\s:.]*`) handle OCR variants gracefully
