#!/usr/bin/env python3
"""
Financial Document Processor - Reference Implementation

This script processes mixed batches of financial documents (PDFs and images) by:
1. Extracting text via OCR/PDF parsing
2. Classifying documents as invoice or other
3. Extracting financial amounts with arithmetic cross-validation
4. Organizing files into output directories
5. Generating summary.csv

Usage:
    python3 process_documents.py

Environment:
    - Requires: Python 3.7+, PyMuPDF, pytesseract, Pillow, tesseract-ocr
    - Install: python3 -m pip install PyMuPDF pytesseract Pillow
    - System: apt-get install tesseract-ocr (Ubuntu/Debian)
"""

import os
import re
import csv
import shutil
from pathlib import Path
from PIL import Image
import pytesseract
import fitz

# Configuration
DOCS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
SUMMARY_PATH = INVOICES_DIR / "summary.csv"


def extract_text_pdf(filepath):
    """Extract text from PDF using PyMuPDF."""
    doc = fitz.open(str(filepath))
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def extract_text_image(filepath):
    """Extract text from image using pytesseract with multiple PSM modes."""
    img = Image.open(str(filepath))
    # Enlarge 2x for better OCR on noisy scans
    img_large = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    
    results = []
    for psm in [6, 11, 3]:
        text = pytesseract.image_to_string(img_large, config=f'--psm {psm}')
        results.append(text)
    
    return select_best_ocr_pass(results)


def extract_text(filepath):
    """Extract text based on file extension."""
    fname = filepath.name.lower()
    if fname.endswith('.pdf'):
        return extract_text_pdf(filepath)
    elif fname.endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff')):
        return extract_text_image(filepath)
    return ""


def select_best_ocr_pass(texts):
    """Select OCR pass with best arithmetic consistency."""
    best_text = None
    best_score = float('inf')
    
    for text in texts:
        subtotal, vat, total = extract_amounts_raw(text)
        
        if subtotal is not None and vat is not None and total is not None:
            score = abs((subtotal + vat) - total)
        elif subtotal is not None and total is not None:
            computed_vat = total - subtotal
            score = 0 if computed_vat > 0 else 1000
        else:
            score = 1000
        
        if score < best_score:
            best_score = score
            best_text = text
    
    if best_score > 100:
        best_text = max(texts, key=len)
    
    return best_text


def parse_amount(text):
    """Parse monetary amount, handling commas and decimals."""
    text = text.strip().replace(',', '').replace('€', '').replace('£', '').replace('$', '')
    try:
        return float(text)
    except ValueError:
        return None


def classify_document(text):
    """
    Classify as 'invoice' or 'other'.
    
    Core principle: Invoice = requests payment (future). 
    Receipt/Reminder = confirms payment (past) or references prior invoice.
    """
    text_lower = text.lower()
    
    # Step 1: Absolute negatives
    if re.search(r'not\s+a\s+tax\s+invoice', text_lower):
        return 'other'
    if re.search(r'approval\s+status\s*:\s*pending', text_lower):
        return 'other'
    
    # Step 2: Payment status (temporal) - receipts confirm payment already made
    if re.search(r'total\s+paid', text_lower):
        return 'other'
    if re.search(r'card\s+payment\s+approved', text_lower):
        return 'other'
    if re.search(r'payment\s+received', text_lower):
        return 'other'
    
    # Payment reminder: chase/dunning letter about prior invoice → other
    if re.search(r'payment\s+reminder', text_lower):
        return 'other'
    
    # Expense reimbursement → other
    if re.search(r'expense\s+reimbursement', text_lower):
        return 'other'
    
    # Step 3: Directionality for ambiguous types
    if re.search(r'remittance\s+(notice|advice)', text_lower):
        # Seller→buyer signals → invoice
        if re.search(r'payable\s+total', text_lower):
            return 'invoice'
        if re.search(r'ship\s+to', text_lower):
            return 'invoice'
        if re.search(r'amount\s+due', text_lower):
            return 'invoice'
        # Buyer→seller signals → other
        if re.search(r'remitted', text_lower):
            return 'other'
        if re.search(r'payment\s+date', text_lower):
            return 'other'
        if re.search(r'paid\s+by', text_lower):
            return 'other'
        # Default
        return 'other'
    
    # Step 4: Positive signals for invoice
    invoice_patterns = [
        r'\binvoice\b',
        r'charge\s+note',
        r'billing\s+statement',
        r'amount\s+due',
        r'total\s+due',
        r'grand\s+total',
        r'please\s+remit',
        r'bill\s+to\b',
        r'tax\s+document',
        r'payable\s+total',
    ]
    
    for pattern in invoice_patterns:
        if re.search(pattern, text_lower):
            return 'invoice'
    
    # Step 5: Fallback for unknown document types
    # If document has monetary amounts and transaction signals, classify as invoice
    has_amounts = bool(re.search(r'[\d,]+\.\d{2}', text))
    has_transaction_signals = bool(re.search(r'(?:customer|client|bill\s+to|ship\s+to)', text_lower))
    
    if has_amounts and has_transaction_signals:
        return 'invoice'
    
    return 'other'


def extract_amounts_raw(text):
    """Extract subtotal, vat, and total using flexible patterns."""
    lines = text.split('\n')
    subtotal = None
    vat = None
    total = None
    
    sep = r'[\s:.]*'
    
    # Total
    for line in lines:
        m = re.search(r'(?:total\s+due|grand\s+total|amount\s+due|total\s+paid|payable\s+total|invoice\s+total)' + sep + r'([\d,]+\.?\d*)', line, re.I)
        if m:
            val = parse_amount(m.group(1))
            if val is not None and val > 0:
                total = val
                break
    
    # Subtotal (flexible for OCR variants)
    for line in lines:
        m = re.search(r'sub\w+' + sep + r'([\d,]+\.?\d*)', line, re.I)
        if m:
            val = parse_amount(m.group(1))
            if val is not None and val > 0:
                subtotal = val
                break
    
    if subtotal is None:
        for line in lines:
            m = re.search(r'net\s+charges' + sep + r'([\d,]+\.?\d*)', line, re.I)
            if m:
                val = parse_amount(m.group(1))
                if val is not None and val > 0:
                    subtotal = val
                    break
    
    # VAT/tax
    for line in lines:
        m = re.search(r'(?:vat|gst|tax|sales\s+tax)\s+\d+(?:\.\d+)?\%' + sep + r'([\d,]+\.?\d+)', line, re.I)
        if m:
            val = parse_amount(m.group(1))
            if val is not None and val > 0:
                vat = val
                break
    
    if vat is None:
        for line in lines:
            m = re.search(r'(?:vat|gst|sales\s+tax|tax)' + sep + r'([\d,]+\.\d{2})', line, re.I)
            if m:
                val = parse_amount(m.group(1))
                if val is not None and val > 0:
                    vat = val
                    break
    
    return subtotal, vat, total


def extract_financial_fields(text):
    """Extract total_amount and vat_amount with arithmetic cross-validation."""
    subtotal, vat, total = extract_amounts_raw(text)
    
    # Arithmetic cross-check
    if subtotal is not None and vat is not None and total is not None:
        expected_total = round(subtotal + vat, 2)
        if abs(expected_total - total) > 0.02:
            recomputed_vat = round(total - subtotal, 2)
            if recomputed_vat > 0:
                vat = recomputed_vat
    
    if vat is None and total is not None and subtotal is not None:
        computed_vat = round(total - subtotal, 2)
        if computed_vat > 0:
            vat = computed_vat
    
    return total, vat


def main():
    """Main processing pipeline."""
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)
    
    files = sorted([f for f in DOCS_DIR.iterdir() if f.is_file()])
    invoices = []
    
    for filepath in files:
        text = extract_text(filepath)
        classification = classify_document(text)
        
        print(f"{filepath.name}: {classification}")
        
        if classification == 'invoice':
            total_amount, vat_amount = extract_financial_fields(text)
            print(f"  Total: {total_amount}, VAT: {vat_amount}")
            invoices.append((filepath.name, total_amount, vat_amount))
            shutil.move(str(filepath), str(INVOICES_DIR / filepath.name))
        else:
            shutil.move(str(filepath), str(OTHER_DIR / filepath.name))
    
    # Write summary.csv
    with open(SUMMARY_PATH, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])
        
        total_sum = 0.0
        vat_sum = 0.0
        
        for fname, total, vat in invoices:
            total_val = total if total is not None else 0.0
            vat_val = vat if vat is not None else 0.0
            writer.writerow([fname, f"{total_val:.2f}", f"{vat_val:.2f}"])
            total_sum += total_val
            vat_sum += vat_val
        
        writer.writerow(['total', f"{total_sum:.2f}", f"{vat_sum:.2f}"])
    
    print(f"\nProcessed {len(invoices)} invoices, {len(files) - len(invoices)} other")
    
    remaining = list(DOCS_DIR.iterdir())
    if remaining:
        print(f"WARNING: {len(remaining)} files still in documents/")
    else:
        print("Documents directory empty ✓")


if __name__ == '__main__':
    main()
