#!/usr/bin/env python3
"""
Financial Document Processor - Reusable Implementation
Classifies mixed financial documents (invoices vs other), extracts monetary fields,
and generates summary reports. Handles PDFs and images with OCR noise.

Usage:
    python process_documents.py --source /path/to/documents --invoices /path/to/invoices --other /path/to/other
"""

import os
import re
import csv
import shutil
import subprocess
import argparse
from pathlib import Path
from itertools import combinations


def extract_text_from_pdf(filepath):
    """Extract text from PDF. Uses pdftotext first, then PyMuPDF, then OCR fallback."""
    text = ""
    # Try pdftotext first
    try:
        result = subprocess.run(
            ["pdftotext", filepath, "-"],
            capture_output=True, text=True, timeout=30
        )
        text = result.stdout.strip()
    except Exception:
        pass
    
    # If pdftotext gave us enough text, use it
    if len(text) > 20:
        return text
    
    # Try PyMuPDF for embedded text
    try:
        import fitz
        doc = fitz.open(filepath)
        pymupdf_text = "".join(page.get_text() for page in doc)
        doc.close()
        if len(pymupdf_text.strip()) > 20:
            return pymupdf_text
    except Exception:
        pass
    
    # OCR fallback: render PDF pages as images and OCR them
    try:
        import fitz
        import pytesseract
        from PIL import Image
        
        doc = fitz.open(filepath)
        ocr_texts = []
        for page in doc:
            # Render page to image at 300 DPI for good OCR quality
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            ocr_text = pytesseract.image_to_string(img)
            ocr_texts.append(ocr_text)
        doc.close()
        return "\n".join(ocr_texts)
    except Exception:
        return text  # Return whatever we got from pdftotext


def extract_text_from_image(filepath):
    """Extract text using multiple OCR approaches for robustness."""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance
        
        img = Image.open(filepath)
        texts = []
        
        # Approach 1: Default configuration
        texts.append(pytesseract.image_to_string(img))
        
        # Approach 2: Grayscale + enhanced contrast + PSM 6
        img_gray = img.convert('L')
        enhancer = ImageEnhance.Contrast(img_gray)
        img_enhanced = enhancer.enhance(2.0)
        texts.append(pytesseract.image_to_string(img_enhanced, config='--psm 6'))
        
        # Approach 3: Original image + PSM 4
        texts.append(pytesseract.image_to_string(img, config='--psm 4'))
        
        return texts
    except Exception:
        return [""]


def extract_text(filepath):
    """Returns list of text variants (multiple for images, single for PDFs)."""
    ext = Path(filepath).suffix.lower()
    if ext == '.pdf':
        return [extract_text_from_pdf(filepath)]
    elif ext in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.gif'):
        return extract_text_from_image(filepath)
    return [""]


def parse_amount(text):
    """
    Parse monetary amount, handling various formats:
    - Standard: 1,234.56 (comma = thousands, period = decimal)
    - European: 1.234,56 (period = thousands, comma = decimal)
    - No separator: 1234.56 or 1234,56
    """
    cleaned = text.strip()
    cleaned = re.sub(r'[€$£¥]', '', cleaned).strip()
    
    has_comma = ',' in cleaned
    has_period = '.' in cleaned
    
    if has_comma and has_period:
        last_dot = cleaned.rfind('.')
        last_comma = cleaned.rfind(',')
        if last_comma > last_dot:
            # European: 1.234,56 -> 1234.56
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            # Standard: 1,234.56 -> 1234.56
            cleaned = cleaned.replace(',', '')
    elif has_comma:
        parts = cleaned.split(',')
        if len(parts) == 2 and len(parts[1]) == 2:
            # Decimal comma: 1234,56 -> 1234.56
            cleaned = cleaned.replace(',', '.')
        else:
            # Thousands comma: 1,234 -> 1234
            cleaned = cleaned.replace(',', '')
    
    match = re.search(r'[\d]+(?:\.\d+)?', cleaned)
    return float(match.group()) if match else 0.0


def extract_all_amounts(text):
    """
    Extract all monetary amounts from text with proper thousands separator handling.
    Uses non-overlapping matches to avoid duplicates.
    """
    amounts = []
    lines = text.split('\n')
    
    for line in lines:
        line_lower = line.lower()
        
        # Comprehensive pattern for monetary amounts (longest match first)
        pattern = r'\b(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2}|\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})\b'
        
        matches = list(re.finditer(pattern, line))
        for match in matches:
            amt_str = match.group(1)
            amt = parse_amount(amt_str)
            if amt > 0:
                amounts.append({
                    'amount': amt,
                    'line': line_lower,
                    'raw': amt_str,
                    'pos': match.start()
                })
    
    # Remove duplicates (same amount and line)
    seen = set()
    unique = []
    for a in amounts:
        key = (a['amount'], a['line'])
        if key not in seen:
            seen.add(key)
            unique.append(a)
    
    return unique


def check_mathematical_consistency(amounts):
    """
    Check if any two amounts sum to a third amount.
    Tolerance: ±2.0 to handle OCR noise.
    This is a strong invoice indicator.
    """
    values = [a['amount'] for a in amounts]
    
    if len(values) < 3:
        return False
    
    # Check all triplets: a + b ≈ c
    for a, b, c in combinations(values, 3):
        if abs((a + b) - c) < 2.0:
            return True
        if abs((a + c) - b) < 2.0:
            return True
        if abs((b + c) - a) < 2.0:
            return True
    
    return False


def fuzzy_match_any(pattern_variants, text):
    """Match against multiple pattern variants (for OCR tolerance)."""
    text_lower = text.lower()
    for pattern in pattern_variants:
        if re.search(pattern, text_lower):
            return True
    return False


def classify_document(text_variants, filename):
    """
    Multi-signal classification using:
    1. Mathematical consistency (subtotal + tax ≈ total)
    2. Payment direction analysis (due vs paid)
    3. Fuzzy keyword matching
    4. Strong negative signals (override)
    """
    primary_text = max(text_variants, key=len)
    text_lower = primary_text.lower()
    
    # Check mathematical consistency across all variants
    has_math_consistency = False
    for text in text_variants:
        amounts = extract_all_amounts(text)
        if check_mathematical_consistency(amounts):
            has_math_consistency = True
            break
    
    # === STRONG NEGATIVE SIGNALS (override everything) ===
    not_invoice_patterns = [
        r'not\s+(a\s+)?(tax\s+)?invoice',
    ]
    if fuzzy_match_any(not_invoice_patterns, text_lower):
        return 'other'
    
    non_invoice_patterns = [
        [r'payment\s+remind[eae]r', r'payment\s+reminder'],
        [r'purchas[eae]\s+ord[eae]r', r'purchase\s+order'],
        [r'expens[eae]\s+reimburs[eae]ment', r'expense\s+reimbursement'],
        [r'reimburs[eae]ment\s+(summary|form|request)'],
        [r'approval\s+status.*p[eae]nding', r'approval.*pending'],
    ]
    
    for variants in non_invoice_patterns:
        if fuzzy_match_any(variants, text_lower):
            return 'other'
    
    # Receipt indicators
    receipt_patterns = [
        [r'r[eae]c[eae]ipt', r'receipt'],
        [r'card\s+paym[eae]nt\s+approv[eae]d'],
        [r'cash\s+r[eae]c[eae]ipt'],
    ]
    
    receipt_score = sum(1 for variants in receipt_patterns if fuzzy_match_any(variants, text_lower))
    
    has_paid = bool(re.search(r'\b(paid|payment\s+approved)\b', text_lower))
    has_due = bool(re.search(r'\b(due|payable|remit|balance\s+due)\b', text_lower))
    
    if receipt_score >= 1 and has_paid and not has_due:
        return 'other'
    
    # === POSITIVE INVOICE SIGNALS ===
    math_score = 2 if has_math_consistency else 0
    
    direction_score = 0
    if has_due and not has_paid:
        direction_score = 2
    elif has_due and has_paid:
        direction_score = 0
    
    invoice_keyword_variants = [
        [r'inv[oa]ic[eae]', r'invoice'],
        [r'billing\s+stat[eae]ment'],
        [r'charg[eae]\s+n[oa]t[eae]', r'charge\s+note', r'charge\s+nate'],
        [r'tax\s+d[oa]cum[eae]nt'],
        [r'r[eae]mittanc[eae]\s+n[oa]tic[eae]'],
        [r'am[oa]unt\s+du[eae]'],
        [r't[oa]tal\s+du[eae]'],
        [r'grand\s+t[oa]tal'],
        [r'payabl[eae]\s+t[oa]tal'],
        [r'pl[eae]as[eae]\s+r[eae]mit'],
        [r'bill\s+t[oa]\b'],
    ]
    
    keyword_score = sum(1 for variants in invoice_keyword_variants if fuzzy_match_any(variants, text_lower))
    
    total_score = math_score + direction_score + keyword_score
    
    # Threshold: need at least 3 points for invoice
    return 'invoice' if total_score >= 3 else 'other'


def extract_financial_fields(text_variants):
    """
    Extract total_amount and vat_amount from invoice text.
    Tries direct extraction first, then computes missing values.
    Handles rate-based tax recovery when tax amount is absent.
    """
    result = {'total_amount': 0.0, 'vat_amount': 0.0}
    
    for text in text_variants:
        text_lower = text.lower()
        
        # Extract tax rate if present (e.g., "VAT 10%", "GST 20%")
        rate = None
        rate_match = re.search(r'(?:vat|tax|gst|sales\s+tax)\s+(\d+(?:\.\d+)?)%', text_lower)
        if rate_match:
            rate = float(rate_match.group(1))
        
        # Total amount patterns
        total_patterns = [
            r'(?:grand\s+total|total\s+due|amount\s+due|payable\s+total|invoice\s+total|total\s+amount|balance\s+due)\s*[:\-]?\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
            r'(?:grand\s+total|total\s+due|amount\s+due|payable\s+total|invoice\s+total|total\s+amount|balance\s+due)\s*[:\-]?\s*(\d+\.\d{2})',
        ]
        
        # Tax amount patterns (flexible for OCR noise)
        tax_patterns = [
            r'(?:vat|tax|gst|sales\s+tax|ast)\s*(?:\d+%)?\s*[:\-]?\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
            r'(?:vat|tax|gst|sales\s+tax|ast)\s*(?:\d+%)?\s*[:\-]?\s*(\d+\.\d{2})',
            r'(?:vat|tax|gst|ast)\s+(\d+\.\d{2})',
        ]
        
        # Subtotal patterns (includes common service/product descriptions)
        subtotal_patterns = [
            r'(?:subtotal|sub\s*total|net\s+(?:charges|amount|total))\s*[:\-]?\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
            r'(?:subtotal|sub\s*total|net\s+(?:charges|amount|total))\s*[:\-]?\s*(\d+\.\d{2})',
            # Common line-item descriptions that represent the pre-tax base amount
            r'(?:services|service|order|retainer|charges?|amount)\s*[:\-]?\s*(\d{1,3}(?:,\d{3})*\.\d{2})',
            r'(?:services|service|order|retainer|charges?|amount)\s*[:\-]?\s*(\d+\.\d{2})',
        ]
        
        # Extract total
        for p in total_patterns:
            m = re.search(p, text_lower)
            if m:
                result['total_amount'] = parse_amount(m.group(1))
                break
        
        # Extract tax
        for p in tax_patterns:
            m = re.search(p, text_lower)
            if m:
                result['vat_amount'] = parse_amount(m.group(1))
                break
        
        # Extract subtotal
        subtotal = 0.0
        for p in subtotal_patterns:
            m = re.search(p, text_lower)
            if m:
                subtotal = parse_amount(m.group(1))
                break
        
        # Strategy 1: If no total found, try subtotal + tax
        if result['total_amount'] == 0.0 and subtotal > 0 and result['vat_amount'] > 0:
            result['total_amount'] = subtotal + result['vat_amount']
        
        # Strategy 2: If no VAT found but have total and subtotal, compute VAT
        if result['vat_amount'] == 0.0 and result['total_amount'] > 0 and subtotal > 0:
            result['vat_amount'] = result['total_amount'] - subtotal
        
        # Strategy 3: Rate-based tax recovery (spec-declared variation)
        # If no VAT found but have rate + subtotal, compute tax from rate
        if result['vat_amount'] == 0.0 and subtotal > 0 and rate is not None:
            result['vat_amount'] = round(subtotal * rate / 100, 2)
            # If total also missing, compute it
            if result['total_amount'] == 0.0:
                result['total_amount'] = subtotal + result['vat_amount']
        
        # Strategy 4: If have total + rate but no subtotal, compute subtotal from total
        if result['total_amount'] > 0 and subtotal == 0 and rate is not None and result['vat_amount'] == 0.0:
            subtotal = round(result['total_amount'] / (1 + rate / 100), 2)
            result['vat_amount'] = round(result['total_amount'] - subtotal, 2)
        
        # If we found both values, we're done
        if result['total_amount'] > 0 and result['vat_amount'] > 0:
            break
    
    return result


def process_documents(source_dir, invoices_dir, other_dir):
    """
    Main processing function.
    
    Args:
        source_dir: Directory containing input documents
        invoices_dir: Directory to move invoices to
        other_dir: Directory to move non-invoices to
    """
    source_path = Path(source_dir)
    invoices_path = Path(invoices_dir)
    other_path = Path(other_dir)
    summary_csv = invoices_path / "summary.csv"
    
    # Create output directories
    invoices_path.mkdir(parents=True, exist_ok=True)
    other_path.mkdir(parents=True, exist_ok=True)
    
    # Get all documents
    docs = []
    for f in sorted(os.listdir(source_path)):
        fp = source_path / f
        if fp.suffix.lower() in ('.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.bmp'):
            docs.append(f)
    
    print(f"Found {len(docs)} documents to process")
    
    invoice_data = []
    
    for doc in docs:
        filepath = source_path / doc
        print(f"\nProcessing: {doc}")
        
        text_variants = extract_text(str(filepath))
        print(f"  Extracted {len(text_variants)} text variant(s)")
        
        classification = classify_document(text_variants, doc)
        print(f"  Classification: {classification}")
        
        if classification == 'invoice':
            fields = extract_financial_fields(text_variants)
            print(f"  Total: {fields['total_amount']}, VAT: {fields['vat_amount']}")
            shutil.move(str(filepath), str(invoices_path / doc))
            invoice_data.append({
                'filename': doc,
                'total_amount': fields['total_amount'],
                'vat_amount': fields['vat_amount'],
            })
        else:
            shutil.move(str(filepath), str(other_path / doc))
    
    # Create summary CSV
    print(f"\nWriting summary.csv with {len(invoice_data)} invoices")
    
    with open(summary_csv, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])
        
        total_sum = 0.0
        vat_sum = 0.0
        
        for row in invoice_data:
            writer.writerow([row['filename'], f"{row['total_amount']:.2f}", f"{row['vat_amount']:.2f}"])
            total_sum += row['total_amount']
            vat_sum += row['vat_amount']
        
        writer.writerow(['total', f"{total_sum:.2f}", f"{vat_sum:.2f}"])
    
    print(f"Total amount sum: {total_sum:.2f}")
    print(f"VAT amount sum: {vat_sum:.2f}")
    
    # Verify source directory is empty
    remaining = os.listdir(source_path)
    if remaining:
        print(f"WARNING: {len(remaining)} files still in source directory: {remaining}")
    else:
        print("Source directory is empty. Processing complete!")


def main():
    parser = argparse.ArgumentParser(
        description='Process financial documents: classify invoices vs other, extract fields, generate summary'
    )
    parser.add_argument(
        '--source',
        required=True,
        help='Source directory containing input documents'
    )
    parser.add_argument(
        '--invoices',
        required=True,
        help='Destination directory for invoices'
    )
    parser.add_argument(
        '--other',
        required=True,
        help='Destination directory for non-invoice documents'
    )
    
    args = parser.parse_args()
    
    process_documents(args.source, args.invoices, args.other)


if __name__ == '__main__':
    main()
