# Financial Document Processing Patterns

## Table of Contents
- [Multi-Tool OCR Pipeline](#multi-tool-ocr-pipeline)
- [Semantic Invoice Classification](#semantic-invoice-classification)
- [Flexible Financial Field Extraction](#flexible-financial-field-extraction)

## Multi-Tool OCR Pipeline
Use multiple extraction tools and preprocessing techniques to handle OCR noise, then cross-verify results for accuracy:
1. **pdftotext**: Use for PDFs with embedded text (fast and accurate).
2. **tesseract**: Use with multiple PSM modes (3, 4, 6, 11, 12) for JPGs to find the best reading.
3. **Image Preprocessing**: For noisy OCR, convert to grayscale, enhance contrast (2.0x), sharpen, scale up 2-3x with LANCZOS, and apply binary thresholding.
4. **PyMuPDF (fitz)**: Extract text directly from PDFs as verification.
5. **Cross-Verification**: Verify extracted amounts using arithmetic consistency (e.g., if OCR misreads VAT, calculate it as total - subtotal).

## Semantic Invoice Classification
Distinguish invoices from similar financial documents by identifying whether the document requests payment (invoice) or confirms/documents payment (non-invoice). Focus on functional purpose rather than just the title.

**Invoice Indicators (Requests Payment):**
- 'Please remit', 'Amount Due', 'Total Due', 'Payable Total'
- Seller-to-buyer relationship: 'Bill To', 'Ship To', 'Customer' with line items and tax.
- Borderline cases like 'Remittance Notice' with 'Payable Total' should be classified as invoices based on content structure requesting payment.

**Non-Invoice Indicators (Confirms Payment / Other):**
- 'This notice is not a tax invoice'
- 'Approval Status: Pending' (Purchase Orders)
- 'Card Payment Approved', 'Total Paid' (Receipts). **Do NOT classify point-of-sale receipts as invoices, even if they list subtotal, tax/VAT, and total paid amounts.**
- Internal expense reports / Expense Reimbursement

## Flexible Financial Field Extraction
Extract `total_amount` and `vat_amount` by recognizing diverse label patterns and handling OCR artifacts through arithmetic inference.

**Total Amount Labels:**
- 'Grand Total', 'Amount Due', 'Payable Total', 'Total Due', 'Total Paid' (if invoice).
- When multiple amount candidates exist, select the final/grand total that includes tax, not intermediate subtotals.

**VAT Amount Labels:**
- 'Tax', 'VAT', 'VAT X%', 'Sales Tax', 'GST', 'VAT Included'.

**Handling OCR Noise & Formatting:**
- Strip currency symbols and handle comma-separated thousands (e.g., '1,408.00' → 1408.00).
- Use arithmetic inference: if VAT is unclear but subtotal and total are readable, calculate `VAT = total - subtotal`.