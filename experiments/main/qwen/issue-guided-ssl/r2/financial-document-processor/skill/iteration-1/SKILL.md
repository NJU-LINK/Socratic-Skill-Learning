---
name: financial-document-processor
description: Process mixed batches of financial documents (PDFs and images) by classifying them as invoices or other document types, extracting financial amounts using arithmetic cross-validation, and organizing them into structured output with summary reports.
---

# Financial Document Processor

A reusable skill for processing mixed batches of financial documents with robust handling of OCR noise, varied document formats, and ambiguous classification scenarios.

## Core Capabilities

### 1. Document Classification
Classifies documents as `invoice` or `other` using **structural financial patterns** rather than simple keyword matching:

**Invoice indicators:**
- Customer/client/bill-to party field
- Goods or services with associated amounts
- Tax/VAT/GST as a separate line item
- Total amount due/payable
- Payment request (explicit or implicit)
- Valid arithmetic: subtotal + tax = total

**Non-invoice indicators:**
- Explicit disclaimer ("not a tax invoice")
- Purchase orders (request-to-buy, not request-for-payment)
- Expense reimbursement summaries (internal accounting)
- Payment reminders (references prior invoice)
- Pending approval status

### 2. Financial Data Extraction
Extracts `total_amount` and `vat_amount` from invoices using **arithmetic cross-validation with decimal recovery**:

- Extracts all monetary values from document text, distinguishing between:
  - **Decimal numbers**: values with explicit decimal points (e.g., "1,280.00", "751.68")
  - **Integer numbers**: values without decimal points (e.g., "483", "5420")
- **Decimal recovery**: For integer numbers ≥100, generates decimal-shifted candidates (/10, /100, /1000) to recover missing decimal points from OCR errors (e.g., "483" → 4.83, "5420" → 54.20)
- Identifies labeled amounts (subtotal, tax, total, net)
- Validates combinations using the identity: `subtotal + tax = total`
- Selects the combination that satisfies arithmetic within tolerance (±0.02)
- Handles OCR noise by testing multiple candidate readings

This technique is critical for noisy OCR outputs where punctuation and digits may be misread. The arithmetic identity serves as a ground-truth constraint that disambiguates conflicting OCR results. Decimal recovery specifically addresses the common OCR failure mode of dropping decimal points.

### 3. Multi-Modal Text Extraction
Handles both PDF and image documents with adaptive strategies:

**PDFs:**
- Primary: `pdftotext` for text-based PDFs
- Fallback 1: PyMuPDF (fitz) for embedded text extraction
- Fallback 2: Render pages as images and OCR (for scanned PDFs)

**Images (JPG, PNG, etc.):**
- Multiple preprocessing strategies (grayscale, 2x resize, sharpening)
- Multiple OCR PSM modes (3, 4, 6, 11, 12)
- Aggregates all OCR results for arithmetic cross-validation to select correct values

### 4. Batch Processing
- Processes all PDF and image files in a source directory
- Moves invoices to `/app/invoices/`
- Moves non-invoices to `/app/other/`
- Generates `summary.csv` with per-invoice rows and a totals row
- Handles variable batch sizes and class balances

## Usage

### Basic Execution
```bash
python3 scripts/process_documents.py
```

### Environment Variables
Customize paths via environment variables:
- `SOURCE_DIR`: Input directory (default: `/app/documents`)
- `INVOICES_DIR`: Invoice output directory (default: `/app/invoices`)
- `OTHER_DIR`: Non-invoice output directory (default: `/app/other`)
- `SUMMARY_PATH`: Summary CSV path (default: `/app/invoices/summary.csv`)

### Example
```bash
export SOURCE_DIR=/app/documents
export INVOICES_DIR=/app/invoices
export OTHER_DIR=/app/other
export SUMMARY_PATH=/app/invoices/summary.csv

python3 scripts/process_documents.py
```

## Output Format

### Directory Structure
```
/app/
├── documents/          # Source (emptied after processing)
├── invoices/           # Invoice documents
│   ├── summary.csv     # Financial summary
│   └── *.pdf|*.jpg     # Invoice files
└── other/              # Non-invoice documents
    └── *.pdf|*.jpg     # Other document files
```

### summary.csv Format
```csv
filename,total_amount,vat_amount
invoice1.pdf,1234.56,98.76
invoice2.jpg,789.00,63.12
total,2023.56,161.88
```

- One row per invoice with extracted amounts
- Final row with `filename=total` and summed amounts
- All amounts formatted to 2 decimal places

## Robustness Features

### Handling OCR Noise
- **Multi-PSM OCR**: Tries multiple page segmentation modes to capture different layout interpretations
- **Preprocessing variants**: Tests grayscale, resized, and sharpened versions
- **Decimal recovery**: For integers ≥100, generates /10, /100, /1000 variants to recover missing decimal points (e.g., "483" → 4.83, "5420" → 54.20)
- **Arithmetic validation**: Uses `subtotal + tax = total` to select correct readings from conflicting OCR results
- **Candidate aggregation**: Collects all number candidates across OCR runs and validates against arithmetic constraints
- **Smart expansion**: Only expands integer numbers (those without decimal points in original text), avoiding false matches with already-correct decimal values

### Handling Varied Document Labels
Documents may use non-standard labels:
- "Tax Document", "Billing Statement", "Remittance Notice", "Charge Note", "Receipt"
- "Grand Total", "Amount Due", "Payable Total", "Total Paid"
- "VAT", "Tax", "GST", "Sales Tax"

The classifier uses structural patterns (customer field + goods/services + tax line + total + payment request) rather than requiring specific keywords.

### Handling Different Numeric Conventions
- Supports: `1,234.56`, `1234.56`, `1234`
- Handles OCR artifacts like missing decimal points (`483` → `4.83`)
- Arithmetic cross-validation resolves ambiguity

### Handling Edge Cases
- **Weak invoice markers**: Documents without "invoice" keyword but with invoice financial structure
- **Overlapping vocabulary**: Non-invoices with financial terms (e.g., "Payment Reminder" with amounts)
- **Multi-page documents**: Extracts text from all pages
- **Mixed PDF types**: Handles text-based, image-based, and hybrid PDFs

## Implementation Details

### Classification Algorithm
1. Check for strong non-invoice signals (disclaimers, purchase orders, reimbursements, reminders)
2. If any non-invoice signal present → classify as `other`
3. Otherwise, count invoice signals:
   - Customer field
   - Goods/services with amounts
   - Tax line
   - Total field
   - Invoice-type label
   - Payment request
   - Arithmetic validation passes
4. If ≥2 invoice signals → classify as `invoice`
5. Otherwise → classify as `other`

### Extraction Algorithm
1. Extract all numbers from text, classifying each as decimal (had decimal point) or integer (no decimal point)
2. Identify labeled amounts by matching line patterns, preserving decimal/integer classification
3. **Generate decimal candidates**: For all integer numbers ≥100, create /10, /100, /1000 variants
4. Try arithmetic cross-validation strategies using combined candidate lists (decimals + expanded integers):
   - **Strategy 1**: Direct match (subtotal + tax = total)
   - **Strategy 2**: Implied subtotal (total - tax = subtotal, check if exists)
   - **Strategy 3**: Implied tax from rate (total - subtotal = tax, check if exists)
   - **Strategy 4**: Fallback (largest total + largest tax)
5. Return first valid match within tolerance

## Dependencies

### Required
- Python 3.7+
- `pdftotext` (poppler-utils)
- `tesseract` (Tesseract OCR)

### Optional (for enhanced functionality)
- `pytesseract` (Python Tesseract wrapper)
- `Pillow` (Python Imaging Library)
- `PyMuPDF` (fitz) - for PDF rendering and fallback extraction

Install optional dependencies:
```bash
pip install pytesseract Pillow PyMuPDF
```

## Limitations and Future Extensions

### Current Limitations
- Assumes single-page documents (multi-page invoices may need page-level aggregation)
- Arithmetic cross-validation requires at least subtotal + tax + total to be present
- Classification accuracy depends on structural pattern quality

### Potential Extensions
- Line-item extraction for detailed invoice analysis
- Multi-currency support
- Vendor/customer database integration
- Confidence scoring for classification and extraction
- Machine learning-based classification for ambiguous cases

## Testing and Validation

The skill has been validated on:
- Text-based PDFs with standard labels
- Scanned images with OCR noise
- Documents with weak or non-standard invoice markers
- Mixed batches with varying invoice/other ratios
- Arithmetic cross-validation across multiple OCR readings

All test cases demonstrate correct classification and amount extraction with arithmetic validation.
