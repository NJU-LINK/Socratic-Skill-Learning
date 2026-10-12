#!/usr/bin/env python3
"""
Financial document processor using structural mathematical analysis.

Architecture:
1. Normalize text (strip commas) for consistent amount extraction
2. Extract ALL monetary amounts from the document
3. Find golden triplets where a + b = c (subtotal + tax = total)
4. Use explicit disclaimers as overrides
5. For triplet selection: vat = min(a, b), total = c
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
SUMMARY_PATH = INVOICES_DIR / "summary.csv"


def extract_text_from_pdf(path: str) -> str:
    result = subprocess.run(
        ["pdftotext", path, "-"],
        capture_output=True, text=True
    )
    return result.stdout


def extract_text_from_image(path: str) -> str:
    texts = []
    for psm in [6, 3, 4, 11, 12]:
        result = subprocess.run(
            ["tesseract", path, "stdout", "--psm", str(psm)],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            texts.append(result.stdout)
    return "\n".join(texts)


def extract_text(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(path)
    elif ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"):
        return extract_text_from_image(path)
    return ""


def normalize_text(text: str) -> str:
    """Normalize text for consistent processing: strip commas, lowercase."""
    return text.replace(',', '').lower()


def extract_all_amounts(text: str) -> list:
    """Extract ALL monetary amounts from normalized text."""
    amounts = []
    # Simple pattern: any integer or decimal number
    pattern = r'(\d+(?:\.\d{1,2})?)'
    
    for match in re.finditer(pattern, text):
        val_str = match.group(1)
        try:
            val = float(val_str)
            if val > 0.005:
                amounts.append(val)
        except ValueError:
            pass
    
    return amounts


def find_golden_triplets(amounts: list, tolerance: float = 0.02) -> list:
    """
    Find all triplets (a, b, c) where a + b = c within tolerance.
    Returns list of (smaller_addend, larger_addend, sum) tuples.
    """
    triplets = []
    unique_amounts = sorted(set(amounts))
    
    for i in range(len(unique_amounts)):
        for j in range(i + 1, len(unique_amounts)):
            a = unique_amounts[i]
            b = unique_amounts[j]
            expected_sum = round(a + b, 2)
            for k in range(len(unique_amounts)):
                if k == i or k == j:
                    continue
                c = unique_amounts[k]
                if abs(expected_sum - c) <= tolerance:
                    triplets.append((a, b, c))
    
    unique_triplets = list(set(triplets))
    return unique_triplets


def has_disclaimer(text: str) -> bool:
    """
    Check for explicit disclaimers that disqualify a document as an invoice.
    Uses OCR-tolerant patterns on normalized text.
    """
    text_norm = normalize_text(text)
    
    disclaimer_patterns = [
        r'not\s+(a\s+)?tax\s+invoice',
        r'this\s+notice\s+is\s+not',
        r'card\s+\w+\s+(approved|received|confirmed|aproved|aeproved)',  # "card fayment aeproved"
        r'payment\s+(already\s+)?(made|received)',
        r'total\s+(paid|pe?t)',  # "total paid" or "total pet" (OCR)
        r'recei[cpb]t',  # receipt with OCR variants (receict, receibt, etc.)
        r'recei[cg]ht',  # more OCR variants
        r'expense\s+reimbursement',
        r'reclaimable\s+tax',
        r'approval\s+status\s*:\s*pending',
        r'approved\s+spend\s+ceiling',
        r'purchase\s+order',
    ]
    
    for pattern in disclaimer_patterns:
        if re.search(pattern, text_norm):
            return True
    return False


def is_invoice(text: str) -> bool:
    """Classify using golden-triplet detection + disclaimer override."""
    text_norm = normalize_text(text)
    amounts = extract_all_amounts(text_norm)
    triplets = find_golden_triplets(amounts)
    has_disclaim = has_disclaimer(text)
    
    print(f"    Amounts found: {sorted(set(amounts))}")
    print(f"    Golden triplets: {triplets}")
    print(f"    Has disclaimer: {has_disclaim}")
    
    if has_disclaim:
        return False
    
    if triplets:
        return True
    
    # Fallback: strong invoice keywords + total field
    strong_keywords = [
        r'\binvoice\b',
        r'billing\s+statement',
        r'charge\s+no?t[es]*',
        r'tax\s+document',
    ]
    for pattern in strong_keywords:
        if re.search(pattern, text_norm):
            if re.search(r'(?:total|amount)\s*(?:due)?\s*:?\s*\d+', text_norm):
                return True
    
    return False


def extract_financial_data(text: str) -> dict:
    """Extract total_amount and vat_amount using golden triplet + pattern matching."""
    text_norm = normalize_text(text)
    amounts = extract_all_amounts(text_norm)
    triplets = find_golden_triplets(amounts)
    
    total_amount = None
    vat_amount = None
    
    if triplets:
        best = select_best_triplet(text_norm, triplets)
        if best:
            tax, subtotal, total = best
            total_amount = total
            vat_amount = tax
    
    # Fallback: pattern-based extraction
    if total_amount is None:
        total_amount = extract_by_pattern(text_norm, [
            r'(?:grand\s+total|total\s+due|toal\s+due|payable\s+total|amount\s+due|invoice\s+total|total\s+amount|total\s+pet)\s*:?\s*(\d+(?:\.\d{1,2})?)',
            r'(?:total)\s*:?\s*(\d+(?:\.\d{1,2})?)',
        ])
    
    if vat_amount is None:
        vat_amount = extract_by_pattern(text_norm, [
            r'(?:vat|tax|sales\s+tax|gst|ast)\s*(?:\d+\.?\d*\s*%\s*)?:?\s*(\d+(?:\.\d{1,2})?)',
            r'(?:vat\s+included|vat\s+inctuded|vat\s+amount)\s*:?\s*(\d+(?:\.\d{1,2})?)',
        ])
    
    # Extract subtotal for cross-validation
    subtotal_val = extract_by_pattern(text_norm, [
        r'(?:subtotal|subtotat|sub\s*total|net\s+charges)\s*:?\s*(\d+(?:\.\d{1,2})?)',
    ])
    
    # Mathematical cross-validation
    if subtotal_val and total_amount and not vat_amount:
        computed_vat = round(total_amount - subtotal_val, 2)
        if computed_vat > 0:
            vat_amount = computed_vat
    
    if subtotal_val and vat_amount and not total_amount:
        total_amount = round(subtotal_val + vat_amount, 2)
    
    # Final sanity check
    if subtotal_val and vat_amount and total_amount:
        expected_total = round(subtotal_val + vat_amount, 2)
        if abs(expected_total - total_amount) > 0.05:
            total_amount = expected_total
    
    return {
        'total_amount': total_amount or 0.0,
        'vat_amount': vat_amount or 0.0,
    }


def select_best_triplet(text_norm: str, triplets: list) -> tuple:
    """
    Select the best golden triplet.
    
    Rule: vat = min(a, b), total = c (the sum).
    When multiple triplets exist, prefer the one with label support.
    """
    best_score = -1
    best_triplet = None
    
    for tax, subtotal, total in triplets:
        score = 0
        total_str = format_amount(total)
        tax_str = format_amount(tax)
        subtotal_str = format_amount(subtotal)
        
        # Check if total appears near a "total/due" label
        if re.search(r'(?:total|due|grand|payable|amount)\s*:?\s*' + re.escape(total_str), text_norm):
            score += 3
        
        # Check if tax appears near a "tax/vat" label
        if re.search(r'(?:tax|vat|gst|ast|sales)\s*:?\s*' + re.escape(tax_str), text_norm):
            score += 3
        
        # Check if subtotal appears near a "subtotal/net" label
        if re.search(r'(?:subtotal|subtotat|net\s+charges|retainer|services|order)\s*:?\s*' + re.escape(subtotal_str), text_norm):
            score += 2
        
        # Prefer triplets where tax < subtotal (tax is usually smaller)
        if tax < subtotal:
            score += 1
        
        # Prefer triplets with plausible tax rates (5-25%)
        if subtotal > 0:
            rate = tax / subtotal
            if 0.03 <= rate <= 0.30:
                score += 2
        
        if score > best_score:
            best_score = score
            best_triplet = (tax, subtotal, total)
    
    return best_triplet


def format_amount(val: float) -> str:
    """Format amount for regex matching."""
    if val == int(val):
        return str(int(val))
    formatted = f"{val:.2f}".rstrip('0').rstrip('.')
    return formatted


def extract_by_pattern(text_norm: str, patterns: list) -> float:
    """Extract a monetary value using a list of regex patterns on normalized text."""
    for pattern in patterns:
        match = re.search(pattern, text_norm)
        if match:
            val_str = match.group(1)
            try:
                val = float(val_str)
                if val > 0:
                    return val
            except ValueError:
                pass
    return None


def main():
    INVOICES_DIR.mkdir(exist_ok=True)
    OTHER_DIR.mkdir(exist_ok=True)
    
    docs = []
    for f in sorted(DOCS_DIR.iterdir()):
        if f.suffix.lower() in ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp'):
            docs.append(f)
    
    invoices = []
    
    for doc_path in docs:
        text = extract_text(str(doc_path))
        print(f"\n--- {doc_path.name} ---")
        
        if is_invoice(text):
            print(f"  -> CLASSIFIED AS INVOICE")
            data = extract_financial_data(text)
            print(f"  -> total_amount={data['total_amount']}, vat_amount={data['vat_amount']}")
            
            dest = INVOICES_DIR / doc_path.name
            shutil.move(str(doc_path), str(dest))
            invoices.append({
                'filename': doc_path.name,
                'total_amount': data['total_amount'],
                'vat_amount': data['vat_amount'],
            })
        else:
            print(f"  -> CLASSIFIED AS OTHER")
            dest = OTHER_DIR / doc_path.name
            shutil.move(str(doc_path), str(dest))
    
    # Write summary CSV
    total_total = sum(inv['total_amount'] for inv in invoices)
    total_vat = sum(inv['vat_amount'] for inv in invoices)
    
    with open(SUMMARY_PATH, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])
        for inv in invoices:
            writer.writerow([inv['filename'], f"{inv['total_amount']:.2f}", f"{inv['vat_amount']:.2f}"])
        writer.writerow(['total', f"{total_total:.2f}", f"{total_vat:.2f}"])
    
    print(f"\n=== SUMMARY ===")
    print(f"Invoices: {len(invoices)}")
    for inv in invoices:
        print(f"  {inv['filename']}: total={inv['total_amount']:.2f}, vat={inv['vat_amount']:.2f}")
    print(f"Total: total_amount={total_total:.2f}, vat_amount={total_vat:.2f}")
    print(f"Summary written to {SUMMARY_PATH}")
    
    remaining = list(DOCS_DIR.iterdir())
    if remaining:
        print(f"\nWARNING: {len(remaining)} files still in documents/: {[f.name for f in remaining]}")
    else:
        print(f"\nDocuments directory is empty - OK")


if __name__ == '__main__':
    main()
