#!/usr/bin/env python3
"""
Financial Document Processor

Processes a batch of mixed business documents (PDFs and images) to:
1. Classify each as invoice or other
2. Extract total_amount and vat_amount from invoices
3. Move files to appropriate directories
4. Generate summary.csv

Usage:
    python3 process_documents.py [--documents-dir DIR] [--invoices-dir DIR] [--other-dir DIR]
"""

import os
import re
import csv
import shutil
import argparse
import sys

# Try to import optional dependencies
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from PIL import Image
    import pytesseract
except ImportError:
    Image = None
    pytesseract = None


def extract_text_pdf(path):
    """Extract text from PDF using PyMuPDF."""
    if fitz is None:
        raise ImportError("PyMuPDF (fitz) is required for PDF processing")
    doc = fitz.open(path)
    text = ''
    for page in doc:
        text += page.get_text() + '\n'
    doc.close()
    return text


def extract_text_image_multi(path):
    """Extract text from image using multiple Tesseract PSM modes."""
    if Image is None or pytesseract is None:
        raise ImportError("PIL and pytesseract are required for image processing")
    img = Image.open(path)
    candidates = []
    for psm in [3, 4, 6]:
        try:
            t = pytesseract.image_to_string(img, config=f'--psm {psm}')
            candidates.append(t)
        except Exception:
            pass
    return candidates if candidates else ['']


def extract_text_multi(path):
    """Extract text from any supported document, returning multiple candidates for images."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf':
        return [extract_text_pdf(path)]
    elif ext in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.gif'):
        return extract_text_image_multi(path)
    return ['']


def classify_document(texts):
    """
    Classify a document as 'invoice' or 'other' using weighted scoring.
    
    Uses multi-candidate merging: checks signals against combined text from all OCR modes.
    Applies weighted scoring to prevent noisy matches from dominating.
    Defaults to 'other' intentionally (safer than false positive invoice).
    """
    combined = ' '.join(texts).lower()
    
    # Score non-invoice signals (check against combined text)
    non_invoice_score = 0
    non_invoice_patterns = [
        (r'\breceipt\b', 5), (r'\brecei[cp]t\b', 4),  # OCR variant
        (r'\btotal paid\b', 4), (r'\bcard payment\b', 3),
        (r'\bpaid\b', 2), (r'\bnot a tax invoice\b', 5),
        (r'\bpurchase order\b', 5), (r'\bexpense reimbursement\b', 5),
        (r'\bpayment reminder\b', 5), (r'\bapproval status:\s*pending\b', 4),
    ]
    for pattern, weight in non_invoice_patterns:
        if re.search(pattern, combined):
            non_invoice_score += weight
    
    # Score invoice signals
    invoice_score = 0
    invoice_patterns = [
        (r'\binvoice\b', 5), (r'\bbilling statement\b', 4),
        (r'\bbill to\b', 3), (r'\bcharge note\b', 4),
        (r'\bremittance notice\b', 4), (r'\bplease remit\b', 4),
        (r'\bamount due\b', 3), (r'\bpayable total\b', 3),
        (r'\btotal due\b', 3), (r'\bgrand total\b', 3),
    ]
    for pattern, weight in invoice_patterns:
        if re.search(pattern, combined):
            invoice_score += weight
    
    # Decide with explicit thresholds
    if non_invoice_score >= 3:
        return 'other'
    if invoice_score >= 3:
        return 'invoice'
    
    # Intentional default: safer to miss an invoice than include non-invoice
    return 'other'


def parse_amount(s):
    """Parse a monetary amount string, handling various formats."""
    if not s:
        return None
    s = s.strip()
    s = re.sub(r'[€$£¥\s]', '', s)
    s = s.replace(',', '')
    try:
        return float(s)
    except ValueError:
        return None


def extract_from_single_text(text):
    """Extract financial fields from a single text candidate."""
    total_amount = None
    vat_amount = None
    subtotal = None
    
    # Total patterns (most specific first)
    total_patterns = [
        r'(?:grand\s+total|payable\s+total|amount\s+due|total\s+due|balance\s+due|net\s+total)[:\s]*[€$£]?\s*([\d,]+\.?\d*)',
        r'(?<!\w)total[:\s]*[€$£]?\s*([\d,]+\.?\d*)',
    ]
    for pattern in total_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = parse_amount(match.group(1))
            if val is not None and val > 0:
                total_amount = val
                break
    
    # VAT/Tax patterns
    vat_patterns = [
        r'(?:VAT|sales\s+tax|GST)[:\s]*(?:\d+%)?[:\s]*[€$£]?\s*([\d,]+\.?\d*)',
        r'(?:tax|vat)[:\s]*[€$£]?\s*([\d,]+\.?\d*)',
        r'(?:vat\s+included|vat\s+amount)[:\s]*[€$£]?\s*([\d,]+\.?\d*)',
    ]
    for pattern in vat_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = parse_amount(match.group(1))
            if val is not None and val > 0:
                vat_amount = val
                break
    
    # Subtotal patterns
    subtotal_patterns = [
        r'subtotal[:\s]*[€$£]?\s*([\d,]+\.?\d*)',
        r'net\s+charges[:\s]*[€$£]?\s*([\d,]+\.?\d*)',
    ]
    for pattern in subtotal_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            val = parse_amount(match.group(1))
            if val is not None and val > 0:
                subtotal = val
                break
    
    return total_amount, vat_amount, subtotal


def extract_contextual_amounts(text, total_amount=None):
    """
    Extract amounts that are likely monetary values, filtering out dates/IDs.
    
    Filters:
    - Skip lines containing date/ref/id/number keywords
    - Constrain to plausible monetary range (within 10x of total if known)
    - This prevents pollution from dates (2026), IDs (10044), OCR artifacts
    """
    amounts = set()
    lines = text.split('\n')
    
    for line in lines:
        # Skip lines that look like dates, IDs, or reference numbers
        if re.search(r'\b(date|ref|id|number|no|doc)[:\s]*\d', line, re.IGNORECASE):
            continue
        
        # Extract amounts from this line
        for match in re.finditer(r'[\d,]+\.?\d*', line):
            parsed = parse_amount(match.group())
            if parsed and parsed > 0:
                # Filter: must be within plausible range
                if total_amount and parsed > total_amount * 10:
                    continue
                amounts.add(parsed)
    
    return amounts


def extract_financial_fields(texts):
    """
    Extract total_amount and vat_amount by merging information across OCR candidates.
    
    Strategy:
    1. Extract from each text candidate independently
    2. Merge results using mode (most common value)
    3. Compute missing values from available data
    4. Cross-validate across context-filtered amounts from all texts
    """
    all_totals = []
    all_vats = []
    all_subtotals = []
    
    for text in texts:
        total, vat, subtotal = extract_from_single_text(text)
        if total is not None:
            all_totals.append(total)
        if vat is not None:
            all_vats.append(vat)
        if subtotal is not None:
            all_subtotals.append(subtotal)
    
    # Pick most common values (mode)
    total_amount = max(set(all_totals), key=all_totals.count) if all_totals else None
    vat_amount = max(set(all_vats), key=all_vats.count) if all_vats else None
    subtotal = max(set(all_subtotals), key=all_subtotals.count) if all_subtotals else None
    
    # Compute VAT from total - subtotal if needed
    if total_amount is not None and vat_amount is None and subtotal is not None:
        computed_vat = round(total_amount - subtotal, 2)
        if computed_vat > 0:
            vat_amount = computed_vat
    
    # Compute from VAT rate if available
    if vat_amount is None:
        for text in texts:
            rate_match = re.search(r'(?:VAT|tax|GST)\s+(\d+(?:\.\d+)?)\s*%', text, re.IGNORECASE)
            if rate_match and subtotal is not None:
                rate = float(rate_match.group(1))
                vat_amount = round(subtotal * rate / 100, 2)
                if total_amount is None:
                    total_amount = round(subtotal + vat_amount, 2)
                break
    
    # Compute total from subtotal + vat
    if total_amount is None and vat_amount is not None and subtotal is not None:
        total_amount = round(subtotal + vat_amount, 2)
    
    # Cross-validate with context-filtered amounts
    if total_amount is not None and vat_amount is None:
        # Collect amounts from all texts, filtered by context
        all_amounts = set()
        for text in texts:
            all_amounts.update(extract_contextual_amounts(text, total_amount))
        
        # Find amount where (total - amount) also exists in filtered set
        candidates = sorted(all_amounts, reverse=True)
        for amt in candidates:
            if 0 < amt < total_amount:
                diff = round(total_amount - amt, 2)
                if 0 < diff < total_amount * 0.5:
                    if diff in all_amounts:
                        vat_amount = diff
                        break
        
        # Fallback: use largest amount < total as implicit subtotal
        if vat_amount is None:
            for amt in candidates:
                if 0 < amt < total_amount:
                    diff = round(total_amount - amt, 2)
                    if 0 < diff < total_amount * 0.5:
                        vat_amount = diff
                        break
    
    return total_amount, vat_amount


def process_documents(documents_dir, invoices_dir, other_dir):
    """Main processing pipeline."""
    os.makedirs(invoices_dir, exist_ok=True)
    os.makedirs(other_dir, exist_ok=True)
    
    results = []
    files = sorted(os.listdir(documents_dir))
    
    for fname in files:
        fpath = os.path.join(documents_dir, fname)
        if not os.path.isfile(fpath):
            continue
        
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ('.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.gif'):
            continue
        
        texts = extract_text_multi(fpath)
        classification = classify_document(texts)
        
        if classification == 'invoice':
            total, vat = extract_financial_fields(texts)
            results.append({
                'filename': fname,
                'total_amount': total if total is not None else 0.0,
                'vat_amount': vat if vat is not None else 0.0,
            })
            shutil.move(fpath, os.path.join(invoices_dir, fname))
        else:
            shutil.move(fpath, os.path.join(other_dir, fname))
    
    # Write summary.csv
    summary_path = os.path.join(invoices_dir, 'summary.csv')
    with open(summary_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])
        
        total_sum = sum(r['total_amount'] for r in results)
        vat_sum = sum(r['vat_amount'] for r in results)
        
        for r in results:
            writer.writerow([r['filename'], f"{r['total_amount']:.2f}", f"{r['vat_amount']:.2f}"])
        
        writer.writerow(['total', f"{total_sum:.2f}", f"{vat_sum:.2f}"])
    
    return results, summary_path


def main():
    parser = argparse.ArgumentParser(description='Process financial documents')
    parser.add_argument('--documents-dir', default='/app/documents/',
                        help='Input documents directory')
    parser.add_argument('--invoices-dir', default='/app/invoices/',
                        help='Output invoices directory')
    parser.add_argument('--other-dir', default='/app/other/',
                        help='Output other documents directory')
    args = parser.parse_args()
    
    results, summary_path = process_documents(
        args.documents_dir, args.invoices_dir, args.other_dir
    )
    
    print(f"Processed {len(results)} invoices")
    print(f"Summary written to {summary_path}")
    
    # Verify documents dir is empty
    remaining = [f for f in os.listdir(args.documents_dir) 
                 if os.path.isfile(os.path.join(args.documents_dir, f))]
    if remaining:
        print(f"WARNING: {len(remaining)} files remain in {args.documents_dir}")
        sys.exit(1)


if __name__ == '__main__':
    main()
