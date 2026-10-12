#!/usr/bin/env python3
"""
Financial Document Processor - Improved Version
Addresses weaknesses identified from iteration 1:
1. Multi-PSM OCR for better text extraction
2. Context-aware amount filtering to reduce noise
3. Robust triplet selection with label proximity scoring
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
    """Extract text from PDF using pdftotext."""
    result = subprocess.run(
        ["pdftotext", str(filepath), "-"],
        capture_output=True, text=True
    )
    return result.stdout


def extract_text_image(filepath):
    """Extract text from image using tesseract with multiple PSM modes."""
    texts = []
    # Use multiple PSM modes to maximize OCR coverage
    for psm in [6, 3, 4, 11, 12]:
        result = subprocess.run(
            ["tesseract", str(filepath), "stdout", "--psm", str(psm)],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            texts.append(result.stdout)
    return "\n".join(texts)


def extract_text(filepath):
    """Extract text from file based on extension."""
    ext = filepath.suffix.lower()
    if ext == '.pdf':
        return extract_text_pdf(filepath)
    elif ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'):
        return extract_text_image(filepath)
    return ""


def normalize_text(text):
    """Normalize text: strip commas, lowercase."""
    text = text.replace(',', '')
    text = text.lower()
    return text


def extract_amounts_with_context(text):
    """
    Extract monetary amounts with their surrounding context.
    Returns list of (amount, line_context) tuples.
    Context helps filter out noise numbers (dates, reference IDs).
    """
    amounts_with_context = []
    
    # Split into lines for context analysis
    lines = text.split('\n')
    
    for line in lines:
        line_lower = line.lower()
        
        # Skip lines that are clearly not monetary (dates, references, etc.)
        # But keep lines with monetary keywords
        monetary_keywords = [
            'total', 'amount', 'due', 'tax', 'vat', 'gst', 'subtotal',
            'net', 'charges', 'price', 'cost', 'fee', 'payment', 'balance',
            'retainer', 'services', 'order', 'freight', 'meals', 'approved',
            'grand', 'payable', 'outstanding', 'prior', 'estimated', 'requested',
            'included', 'pet', 'paid'
        ]
        
        has_monetary_context = any(kw in line_lower for kw in monetary_keywords)
        
        # Extract numbers from this line
        numbers = re.findall(r'(\d+(?:\.\d{1,2})?)', line)
        
        for num_str in numbers:
            try:
                num = float(num_str)
                if num > 0.005:  # Skip tiny numbers
                    # Keep the number if it has monetary context
                    # or if it looks like a monetary amount (has decimal point)
                    if has_monetary_context or '.' in num_str:
                        amounts_with_context.append((num, line_lower))
            except ValueError:
                pass
    
    return amounts_with_context


def extract_amounts(amounts_with_context):
    """Extract just the amounts from context tuples."""
    return [amt for amt, ctx in amounts_with_context]


def find_golden_triplets(amounts, tolerance=0.02):
    """
    Find triplets (a, b, c) where a + b ≈ c within tolerance.
    Returns list of (smaller_addend, larger_addend, sum) tuples.
    """
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
                    # Ensure c is the largest (it's the total)
                    if c >= a and c >= b:
                        triplets.append((min(a, b), max(a, b), c))
    
    # Deduplicate
    unique_triplets = list(set(triplets))
    return unique_triplets


def has_disclaimer(text):
    """Check for explicit disclaimers that disqualify as invoice."""
    text_lower = text.lower()
    
    # Receipt / payment confirmation patterns
    receipt_patterns = [
        r'card\s+\w+\s+(approved|aproved|aeproved)',  # "card payment approved" with OCR variants
        r'total\s+(paid|pe?t)',                         # "total paid" / "total pet"
        r'recei[cpb]t',                                  # "receipt" with OCR variants
        r'recei[cg]ht',                                  # more OCR variants
    ]
    
    # Non-invoice document patterns
    non_invoice_patterns = [
        r'not\s+(a\s+)?tax\s+invoice',                  # "not a tax invoice"
        r'this\s+notice\s+is\s+not',                    # partial disclaimer
        r'expense\s+reimbursement',                     # internal document
        r'reclaimable\s+tax',                           # reimbursement signal
        r'approval\s+status\s*:\s*pending',             # purchase order
        r'approved\s+spend\s+ceiling',                  # purchase order
        r'purchase\s+order',                            # PO document
    ]
    
    for pattern in receipt_patterns + non_invoice_patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def score_triplet(triplet, amounts_with_context):
    """
    Score a triplet based on label proximity in the original text.
    Higher score = more likely to be the correct invoice triplet.
    """
    tax_val, subtotal_val, total_val = triplet
    score = 0
    
    # Check each amount's context for relevant labels
    for amt, ctx in amounts_with_context:
        # Check if total value appears near total-related labels
        if abs(amt - total_val) < 0.01:
            if any(kw in ctx for kw in ['total', 'due', 'grand', 'payable', 'amount', 'pet', 'paid']):
                score += 5
        
        # Check if tax value appears near tax-related labels
        if abs(amt - tax_val) < 0.01:
            if any(kw in ctx for kw in ['tax', 'vat', 'gst', 'ast', 'sales', 'included']):
                score += 5
        
        # Check if subtotal value appears near subtotal-related labels
        if abs(amt - subtotal_val) < 0.01:
            if any(kw in ctx for kw in ['subtotal', 'subtotat', 'net charges', 'retainer', 
                                        'services', 'order', 'freight', 'meals', 'approved']):
                score += 4
    
    # Prefer triplets where tax < subtotal (tax is usually smaller)
    if tax_val < subtotal_val:
        score += 2
    
    # Prefer triplets with plausible tax rates (3% - 30%)
    if subtotal_val > 0:
        rate = tax_val / subtotal_val
        if 0.03 <= rate <= 0.30:
            score += 3
    
    # Prefer larger amounts (more likely to be real invoice amounts vs noise)
    score += min(total_val / 1000, 2)  # Cap at 2 points
    
    return score


def classify_and_extract(filepath):
    """Classify document and extract financial data."""
    raw_text = extract_text(filepath)
    text = normalize_text(raw_text)
    
    # Extract amounts with context for better filtering
    amounts_with_context = extract_amounts_with_context(text)
    amounts = extract_amounts(amounts_with_context)
    
    # Check disclaimer first (overrides everything)
    if has_disclaimer(text):
        return False, None, None
    
    # Find golden triplets
    triplets = find_golden_triplets(amounts)
    
    if triplets:
        # Score and select best triplet
        best_triplet = max(triplets, key=lambda t: score_triplet(t, amounts_with_context))
        vat_amount = best_triplet[0]  # smaller addend is tax
        total_amount = best_triplet[2]  # sum is total
        return True, total_amount, vat_amount
    
    # Fallback: keyword-based classification
    invoice_keywords = ['invoice', 'billing', 'bill to', 'charge', 'tax document',
                        'remittance', 'statement', 'amount due', 'total due',
                        'grand total', 'payable total']
    
    has_keywords = any(kw in text for kw in invoice_keywords)
    
    # Check for total field
    total_patterns = ['total', 'amount due', 'grand total', 'payable total', 'total due']
    has_total = any(p in text for p in total_patterns)
    
    if has_keywords and has_total:
        # Try to extract from explicit labels
        total_amount = None
        vat_amount = None
        
        # Try to find explicit total
        for pattern in [r'grand\s+total\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'total\s+due\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'toal\s+due\s*:\s*(\d+(?:\.\d{1,2})?)',  # OCR variant
                       r'amount\s+due\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'payable\s+total\s*:\s*(\d+(?:\.\d{1,2})?)']:
            m = re.search(pattern, text)
            if m:
                total_amount = float(m.group(1))
                break
        
        # Try to find explicit VAT/tax
        for pattern in [r'vat\s*(?:\d+%?)?\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'tax\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'ast\s+(\d+(?:\.\d{1,2})?)',  # OCR variant of "tax"
                       r'sales\s+tax\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'gst\s*:\s*(\d+(?:\.\d{1,2})?)']:
            m = re.search(pattern, text)
            if m:
                vat_amount = float(m.group(1))
                break
        
        if total_amount is not None and vat_amount is not None:
            return True, total_amount, vat_amount
        
        # Try mathematical inference
        subtotal = None
        for pattern in [r'subtotal\s*:\s*(\d+(?:\.\d{1,2})?)',
                       r'subtotat\s*:\s*(\d+(?:\.\d{1,2})?)',  # OCR variant
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
    # Create output directories
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get all PDF and image files
    files = []
    for f in sorted(DOCS_DIR.iterdir()):
        if f.suffix.lower() in ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'):
            files.append(f)
    
    invoice_rows = []
    
    for filepath in files:
        print(f"Processing: {filepath.name}")
        is_invoice, total_amount, vat_amount = classify_and_extract(filepath)
        
        if is_invoice:
            print(f"  → INVOICE (total={total_amount}, vat={vat_amount})")
            dest = INVOICES_DIR / filepath.name
            shutil.move(str(filepath), str(dest))
            invoice_rows.append({
                'filename': filepath.name,
                'total_amount': f"{total_amount:.2f}",
                'vat_amount': f"{vat_amount:.2f}"
            })
        else:
            print(f"  → OTHER")
            dest = OTHER_DIR / filepath.name
            shutil.move(str(filepath), str(dest))
    
    # Write summary CSV
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
    
    # Verify documents dir is empty
    remaining = list(DOCS_DIR.iterdir())
    if remaining:
        print(f"WARNING: {len(remaining)} files remain in documents/")
    else:
        print("All documents processed. /app/documents/ is empty.")
    
    print(f"\nSummary CSV written to {SUMMARY_CSV}")
    print(f"Invoices: {len(invoice_rows)}")
    print(f"Total amount: {total_total:.2f}")
    print(f"Total VAT: {total_vat:.2f}")


if __name__ == '__main__':
    main()
