#!/usr/bin/env python3
"""
Financial Document Processor - Iteration 3
Key improvement: Date noise filtering in amount extraction
"""

import os
import re
import csv
import shutil
import subprocess
from pathlib import Path

DOCS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
SUMMARY_CSV = INVOICES_DIR / "summary.csv"


def extract_text_pdf(filepath):
    result = subprocess.run(
        ["pdftotext", str(filepath), "-"],
        capture_output=True, text=True
    )
    return result.stdout


def extract_text_image(filepath):
    texts = []
    for psm in [6, 3, 4, 11, 12]:
        result = subprocess.run(
            ["tesseract", str(filepath), "stdout", "--psm", str(psm)],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            texts.append(result.stdout)
    return "\n".join(texts)


def extract_text(filepath):
    ext = filepath.suffix.lower()
    if ext == '.pdf':
        return extract_text_pdf(filepath)
    elif ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'):
        return extract_text_image(filepath)
    return ""


def normalize_text(text):
    text = text.replace(',', '')
    text = text.lower()
    return text


def is_date_line(line):
    """Check if a line contains date-like patterns."""
    date_patterns = [
        r'\bdate\b',
        r'\bissued\b',
        r'\bdispatch\b',
        r'\bservice\s+date\b',
        r'\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}',  # YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
        r'\d{1,2}[-/\.]\d{1,2}[-/\.]\d{4}',  # DD-MM-YYYY, etc.
    ]
    line_lower = line.lower()
    return any(re.search(p, line_lower) for p in date_patterns)


def extract_amounts_with_context(text):
    """Extract monetary amounts with context, filtering out date noise."""
    amounts_with_context = []
    lines = text.split('\n')
    
    monetary_keywords = [
        'total', 'amount', 'due', 'tax', 'vat', 'gst', 'subtotal',
        'net', 'charges', 'price', 'cost', 'fee', 'payment', 'balance',
        'retainer', 'services', 'order', 'freight', 'meals', 'approved',
        'grand', 'payable', 'outstanding', 'prior', 'estimated', 'requested',
        'included', 'pet', 'paid'
    ]
    
    for line in lines:
        line_lower = line.lower()
        
        # Skip date lines entirely - they contain noise numbers like 2026.02
        if is_date_line(line):
            continue
        
        has_monetary_context = any(kw in line_lower for kw in monetary_keywords)
        
        numbers = re.findall(r'(\d+(?:\.\d{1,2})?)', line)
        
        for num_str in numbers:
            try:
                num = float(num_str)
                if num > 0.005:
                    if has_monetary_context or '.' in num_str:
                        amounts_with_context.append((num, line_lower))
            except ValueError:
                pass
    
    return amounts_with_context


def extract_amounts(amounts_with_context):
    return [amt for amt, ctx in amounts_with_context]


def find_golden_triplets(amounts, tolerance=0.02):
    unique_amounts = sorted(set(amounts))
    triplets = []
    
    for i, a in enumerate(unique_amounts):
        for j, b in enumerate(unique_amounts):
            if i >= j:
                continue
            expected_sum = round(a + b, 2)
            for k, c in enumerate(unique_amounts):
                if k == i or k == j:
                    continue
                if abs(expected_sum - c) <= tolerance:
                    if c >= a and c >= b:
                        triplets.append((min(a, b), max(a, b), c))
    
    unique_triplets = list(set(triplets))
    return unique_triplets


def has_disclaimer(text):
    text_lower = text.lower()
    
    receipt_patterns = [
        r'card\s+\w+\s+(approved|aproved|aeproved)',
        r'total\s+(paid|pe?t)',
        r'recei[cpb]t',
        r'recei[cg]ht',
    ]
    
    non_invoice_patterns = [
        r'not\s+(a\s+)?tax\s+invoice',
        r'this\s+notice\s+is\s+not',
        r'expense\s+reimbursement',
        r'reclaimable\s+tax',
        r'approval\s+status\s*:\s*pending',
        r'approved\s+spend\s+ceiling',
        r'purchase\s+order',
    ]
    
    for pattern in receipt_patterns + non_invoice_patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def score_triplet(triplet, amounts_with_context):
    tax_val, subtotal_val, total_val = triplet
    score = 0
    
    for amt, ctx in amounts_with_context:
        if abs(amt - total_val) < 0.01:
            if any(kw in ctx for kw in ['total', 'due', 'grand', 'payable', 'amount', 'pet', 'paid']):
                score += 5
        
        if abs(amt - tax_val) < 0.01:
            if any(kw in ctx for kw in ['tax', 'vat', 'gst', 'ast', 'sales', 'included']):
                score += 5
        
        if abs(amt - subtotal_val) < 0.01:
            if any(kw in ctx for kw in ['subtotal', 'subtotat', 'net charges', 'retainer', 
                                        'services', 'order', 'freight', 'meals', 'approved']):
                score += 4
    
    if tax_val < subtotal_val:
        score += 2
    
    if subtotal_val > 0:
        rate = tax_val / subtotal_val
        if 0.03 <= rate <= 0.30:
            score += 3
    
    score += min(total_val / 1000, 2)
    
    return score


def classify_and_extract(filepath):
    raw_text = extract_text(filepath)
    text = normalize_text(raw_text)
    
    amounts_with_context = extract_amounts_with_context(text)
    amounts = extract_amounts(amounts_with_context)
    
    if has_disclaimer(text):
        return False, None, None
    
    triplets = find_golden_triplets(amounts)
    
    if triplets:
        best_triplet = max(triplets, key=lambda t: score_triplet(t, amounts_with_context))
        vat_amount = best_triplet[0]
        total_amount = best_triplet[2]
        return True, total_amount, vat_amount
    
    # Fallback: keyword-based classification
    invoice_keywords = ['invoice', 'billing', 'bill to', 'charge', 'tax document',
                        'remittance', 'statement', 'amount due', 'total due',
                        'grand total', 'payable total']
    
    has_keywords = any(kw in text for kw in invoice_keywords)
    
    total_patterns = ['total', 'amount due', 'grand total', 'payable total', 'total due']
    has_total = any(p in text for p in total_patterns)
    
    if has_keywords and has_total:
        total_amount = None
        vat_amount = None
        
        for pattern in [r'grand\s+total\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'total\s+due\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'toal\s+due\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'amount\s+due\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'payable\s+total\s*:\s*(\d+(?:\.\d{1,2})?)']:
            m = re.search(pattern, text)
            if m:
                total_amount = float(m.group(1))
                break
        
        for pattern in [r'vat\s*(?:\d+%?)?\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'tax\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'ast\s+(\d+(?:\.\d{1,2})?)',
                       r'sales\s+tax\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'gst\s*:\s*(\d+(?:\.\d{1,2})?)']:
            m = re.search(pattern, text)
            if m:
                vat_amount = float(m.group(1))
                break
        
        if total_amount is not None and vat_amount is not None:
            return True, total_amount, vat_amount
        
        subtotal = None
        for pattern in [r'subtotal\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'subtotat\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'net\s+charges\s*:\s*(\d+(?:\.\d{1,2})?)']:
            m = re.search(pattern, text)
            if m:
                subtotal = float(m.group(1))
                break
        
        if total_amount is not None and subtotal is not None:
            vat_amount = round(total_amount - subtotal, 2)
            return True, total_amount, vat_amount
        
        if subtotal is not None and vat_amount is not None:
            total_amount = round(subtotal + vat_amount, 2)
            return True, total_amount, vat_amount
    
    return False, None, None


def main():
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)
    
    files = []
    for f in sorted(DOCS_DIR.iterdir()):
        if f.suffix.lower() in ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'):
            files.append(f)
    
    invoice_rows = []
    
    for filepath in files:
        is_invoice, total_amount, vat_amount = classify_and_extract(filepath)
        
        if is_invoice:
            dest = INVOICES_DIR / filepath.name
            shutil.move(str(filepath), str(dest))
            invoice_rows.append({
                'filename': filepath.name,
                'total_amount': f"{total_amount:.2f}",
                'vat_amount': f"{vat_amount:.2f}"
            })
        else:
            dest = OTHER_DIR / filepath.name
            shutil.move(str(filepath), str(dest))
    
    total_total = sum(float(r['total_amount']) for r in invoice_rows)
    total_vat = sum(float(r['vat_amount']) for r in invoice_rows)
    
    with open(SUMMARY_CSV, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['filename', 'total_amount', 'vat_amount'])
        writer.writeheader()
        for row in invoice_rows:
            writer.writerow(row)
        writer.writerow({
            'filename': 'total',
            'total_amount': f"{total_total:.2f}",
            'vat_amount': f"{total_vat:.2f}"
        })
    
    remaining = list(DOCS_DIR.iterdir())
    if remaining:
        print(f"WARNING: {len(remaining)} files remain in documents/")
    else:
        print("All documents processed. /app/documents/ is empty.")


if __name__ == '__main__':
    main()
