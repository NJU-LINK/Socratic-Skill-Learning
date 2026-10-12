#!/usr/bin/env python3
"""
Financial document processor with robust OCR-decimal recovery.
Classifies documents as invoice/other, extracts amounts, produces summary.csv.
"""

import os
import re
import csv
import shutil
import subprocess
import tempfile
import itertools
from pathlib import Path
from PIL import Image, ImageFilter, ImageOps

DOCS_DIR = Path('/app/documents')
INVOICES_DIR = Path('/app/invoices')
OTHER_DIR = Path('/app/other')
SUMMARY_CSV = INVOICES_DIR / 'summary.csv'


def extract_text_image_pdf(fp):
    """OCR fallback for scanned PDFs - convert pages to images then OCR."""
    text_parts = []
    with tempfile.TemporaryDirectory() as tmpdir:
        # Convert PDF pages to PNG images at 300 DPI
        r = subprocess.run(['pdftoppm', '-png', '-r', '300', str(fp), f'{tmpdir}/page'], 
                          capture_output=True, text=True)
        if r.returncode != 0:
            return ''
        # OCR each page
        for img_file in sorted(Path(tmpdir).glob('page-*.png')):
            page_text = extract_text_image(img_file)
            text_parts.append(page_text)
    return '\n'.join(text_parts)


def extract_text_pdf(fp):
    r = subprocess.run(['pdftotext', str(fp), '-'], capture_output=True, text=True)
    text = r.stdout.strip()
    # Fallback to OCR if pdftotext returns too little text (scanned PDF)
    if len(text) < 20:
        return extract_text_image_pdf(fp)
    return text


def extract_text_image(fp):
    img = Image.open(fp).convert('L')
    img = ImageOps.autocontrast(img)
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = img.filter(ImageFilter.SHARPEN)
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as t:
        tp = t.name
        img.save(tp)
    try:
        r = subprocess.run(['tesseract', tp, 'stdout'], capture_output=True, text=True)
        return r.stdout.strip()
    finally:
        os.unlink(tp)


def extract_text(fp):
    s = fp.suffix.lower()
    if s == '.pdf':
        return extract_text_pdf(fp)
    elif s in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp'):
        return extract_text_image(fp)
    return ''


def normalize_ocr(text):
    """Fix common OCR errors with expanded dictionary"""
    reps = {
        'subtotat': 'subtotal', 'subtotet': 'subtotal', 'subtota1': 'subtotal',
        'inctuded': 'included', 'inctudedct': 'included', 'inc1uded': 'included',
        'taxi': 'tax', 'taxt': 'tax', 'tota1': 'total',
        'suramary': 'summary', 'surmary': 'summary',
        'reimbursemen': 'reimbursement', 'reimbursment': 'reimbursement',
        'eynense': 'expense', 'expence': 'expense',
        'mats': 'notes', 'note5': 'notes',
        'bi11': 'bill', 'sh1p': 'ship',
        'cust0mer': 'customer', 'c1ient': 'client'
    }
    t = text.lower()
    for w, r in reps.items():
        t = t.replace(w, r)
    return t


def classify_document(text):
    """
    Classify document as invoice (True) or other (False).
    
    Uses hard negatives, structural prerequisite gate, and weighted scoring.
    """
    tn = normalize_ocr(text)
    
    # Hard negatives first
    negatives = [
        r'not a tax invoice',
        r'not an invoice',
        r'purchase order',
        r'expense reimbursement',
        r'payment reminder',
        r'approval status.*pending',
        r'reclaimable tax'
    ]
    for p in negatives:
        if re.search(p, tn):
            return False
    
    # IMPROVED: More flexible structural markers
    # Reference numbers - more variations
    structural_markers = [
        r'(?:ref|reference|invoice\s*(?:no|number|#)|order\s*(?:no|number)|doc(?:ument)?\s*(?:id|ref|no|number)|account\s*(?:no|number))[\s.:]*[\w-]+',
        # Dates - multiple formats
        r'(?:date|issued|dispatch|invoice\s+date)\s*[:.]?\s*(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4}|\w+\s+\d{1,2},?\s+\d{4})',
        # Party identifiers - more variations
        r'(?:bill\s*to|ship\s*to|sold\s*to|deliver\s*to|client|customer|attention|attn)',
    ]
    has_structural = any(re.search(p, tn) for p in structural_markers)
    
    if not has_structural:
        return False  # No structural markers → not an invoice
    
    # Positive cues (weighted scoring)
    positives = [
        ('invoice', 3),
        ('billing statement', 3),
        ('tax document', 2),
        ('charge notes?', 3),
        ('remittance notice', 2),
        ('amount due', 2),
        ('total due', 2),
        ('total paid', 2),
        ('grand total', 3),
        ('payable total', 3),
        ('balance due', 3),
        ('vat', 2),
        ('sales tax', 2),
        ('gst', 2),
        ('subtotal', 2),
        ('bill to', 2),
        ('net amount', 2),
        ('amount payable', 2),
        ('ship to', 1),
        ('customer', 1),
        ('client', 1),
        ('doc ref', 1),
        ('issue date', 1),
        ('sold to', 1)
    ]
    score = sum(w for p, w in positives if re.search(p, tn))
    return score >= 5


def decimal_variants(raw_str):
    """Generate candidate decimal values for OCR-garbled amounts"""
    cleaned = raw_str.replace(',', '').replace('$', '').strip()
    if '.' in cleaned:
        try:
            return [float(cleaned)]
        except ValueError:
            return []
    digits = re.sub(r'[^\d]', '', cleaned)
    if not digits:
        return []
    candidates = [float(digits)]
    for i in range(1, min(3, len(digits))):
        if i < len(digits):
            candidates.append(float(digits[:-i] + '.' + digits[-i:]))
    return candidates


def extract_financial_data(text):
    """
    Extract total_amount and vat_amount with OCR-decimal recovery.
    Uses arithmetic cross-check: subtotal + tax ≈ total.
    """
    tn = normalize_ocr(text)
    lines = tn.split('\n')
    subtotal_raw = vat_raw = total_raw = None

    for line in lines:
        # Total - more variations, use (?<!\w)total to avoid matching "subtotal"
        m = re.search(r'(?:grand\s+total|total\s+due|amount\s+due|payable\s+total|total\s+paid|invoice\s+total|balance\s+due|net\s+amount|amount\s+payable|(?<!\w)total)[:\s]*\$?([\d,]+\.?\d*)', line)
        if m:
            total_raw = m.group(1)
            continue
        m = re.search(r'subtotal[:\s]*\$?([\d,]+\.?\d*)', line)
        if m:
            subtotal_raw = m.group(1)
            continue
        # VAT regex: bridge tolerates words like "included"; \b(?!%) skips rate percentages
        m = re.search(r'(?:vat|tax|gst|sales\s+tax)[\w\s.%:]*?\$?([\d,]+\.?\d*)\b(?!%)', line)
        if m:
            vat_raw = m.group(1)
            continue

    sub_l = decimal_variants(subtotal_raw) if subtotal_raw else []
    vat_l = decimal_variants(vat_raw) if vat_raw else []
    tot_l = decimal_variants(total_raw) if total_raw else []

    if sub_l and vat_l and tot_l:
        best = None
        for s, v, t in itertools.product(sub_l, vat_l, tot_l):
            if abs(s + v - t) < 0.02 and 0 < t < 100000:
                if best is None or t < best[2]:
                    best = (s, v, t)
        if best:
            return {'total_amount': best[2], 'vat_amount': best[1]}

    sub = sub_l[0] if sub_l else None
    vat = vat_l[0] if vat_l else None
    tot = tot_l[0] if tot_l else None

    if sub is not None and tot is not None and vat is None:
        if tot > sub:
            vat = round(tot - sub, 2)
    if sub is not None and vat is not None and tot is None:
        tot = round(sub + vat, 2)

    return {'total_amount': tot, 'vat_amount': vat}


def main():
    INVOICES_DIR.mkdir(exist_ok=True)
    OTHER_DIR.mkdir(exist_ok=True)
    invoice_data = []

    for doc_path in sorted(DOCS_DIR.iterdir()):
        if doc_path.suffix.lower() not in ('.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.bmp'):
            continue
        print(f'Processing: {doc_path.name}')
        text = extract_text(doc_path)
        is_inv = classify_document(text)
        if is_inv:
            print(f'  -> INVOICE')
            data = extract_financial_data(text)
            print(f'    total={data["total_amount"]}, vat={data["vat_amount"]}')
            shutil.move(str(doc_path), str(INVOICES_DIR / doc_path.name))
            invoice_data.append({
                'filename': doc_path.name,
                'total_amount': data['total_amount'],
                'vat_amount': data['vat_amount']
            })
        else:
            print(f'  -> OTHER')
            shutil.move(str(doc_path), str(OTHER_DIR / doc_path.name))

    with open(SUMMARY_CSV, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['filename', 'total_amount', 'vat_amount'])
        ts = vs = 0.0
        for row in invoice_data:
            w.writerow([row['filename'], row['total_amount'], row['vat_amount']])
            ts += row['total_amount'] or 0
            vs += row['vat_amount'] or 0
        w.writerow(['total', round(ts, 2), round(vs, 2)])

    print(f'\nSummary written. Invoices: {len(invoice_data)}, Grand total: {ts}, Total VAT: {vs}')


if __name__ == '__main__':
    main()
