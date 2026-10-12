---
name: financial-document-processor
description: General starting point for solving tasks in the financial-document-processor family.
---

# financial-document-processor

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Workflow

1. **Extract Text**: Use a multi-tool OCR pipeline (pdftotext, tesseract, PyMuPDF) with image preprocessing for noisy documents. Cross-verify results.
2. **Classify Document**: Determine if the document is an invoice (requests payment) or a non-invoice (confirms payment, PO, receipt) based on semantic cues, not just titles.
3. **Extract Fields**: Extract `total_amount` and `vat_amount` using flexible label matching and arithmetic inference (e.g., VAT = total - subtotal) to handle OCR noise.

For detailed patterns, indicators, and preprocessing techniques, see [references/processing-patterns.md](references/processing-patterns.md).


## Environment State Reset

Ensure a clean state before re-running iteratively refined file-processing scripts:
- Move processed files from output directories (e.g., `/app/invoices`, `/app/other`) back to the input directory (`/app/documents`).
- Delete generated artifacts (e.g., `summary.csv`).
- Use `shutil.move` and `os.remove` to prevent file-not-found errors and duplicate processing.