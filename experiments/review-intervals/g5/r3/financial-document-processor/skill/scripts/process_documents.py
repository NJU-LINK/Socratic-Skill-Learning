#!/usr/bin/env python3
"""
Financial document processor: classify, extract amounts, route, and summarize.
Handles PDFs (text-embedded) and JPGs/PNGs (OCR with multi-mode consensus).
"""

import os
import re
import csv
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageEnhance
import pytesseract
from collections import Counter

DOCS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
SUMMARY_CSV = INVOICES_DIR / "summary.csv"


# --- Text Extraction ---

def extract_text_pdf(path: Path) -> tuple:
    """Extract text from a PDF. Returns (best_text, all_texts)."""
    try:
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True, text=True, timeout=30
        )
        text = result.stdout
        return text, [text]
    except Exception:
        try:
            import fitz
            doc = fitz.open(str(path))
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text, [text]
        except Exception:
            return "", []


def extract_text_image(path: Path) -> tuple:
    """Extract text from an image using pytesseract with multiple PSM modes."""
    try:
        img = Image.open(path)
        
        all_texts = []
        for psm in [3, 6, 11]:
            try:
                text = pytesseract.image_to_string(img, config=f'--psm {psm}')
                all_texts.append(text)
            except Exception:
                continue
        
        # Try light preprocessing if all modes give little text
        if all(len(t.strip()) < 20 for t in all_texts):
            img_gray = img.convert('L')
            img_enhanced = ImageEnhance.Contrast(img_gray).enhance(1.3)
            for psm in [6, 11]:
                try:
                    text = pytesseract.image_to_string(img_enhanced, config=f'--psm {psm}')
                    all_texts.append(text)
                except Exception:
                    continue
        
        best_text = max(all_texts, key=lambda t: len(t.strip())) if all_texts else ""
        return best_text, all_texts
    except Exception:
        return "", []


def extract_text(path: Path) -> tuple:
    """Returns (best_text, all_texts) tuple."""
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        return extract_text_pdf(path)
    elif suffix in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.gif'):
        return extract_text_image(path)
    else:
        return "", []


# --- Classification ---

def fuzzy_contains(text: str, target: str, max_distance: int = 2) -> bool:
    """Check if text contains target with up to max_distance character differences."""
    text_lower = text.lower()
    target_lower = target.lower()
    
    if target_lower in text_lower:
        return True
    
    target_len = len(target_lower)
    for i in range(len(text_lower) - target_len + 1):
        window = text_lower[i:i + target_len]
        distance = sum(1 for a, b in zip(window, target_lower) if a != b)
        if distance <= max_distance:
            return True
    
    return False


def classify_document(text: str) -> str:
    """Classify a document as 'invoice' or 'other' based on content signals."""
    text_lower = text.lower()
    
    # Anti-signals
    anti_signals = [
        "this notice is not a tax invoice",
        "this is not an invoice",
        "not a valid invoice",
    ]
    for anti in anti_signals:
        if anti in text_lower:
            return "other"
    
    # Non-invoice types
    non_invoice_types = [
        "purchase order",
        "expense reimbursement",
        "reimbursement summary",
        "bank statement",
        "delivery note",
        "packing slip",
        "shipping manifest",
    ]
    for nit in non_invoice_types:
        if nit in text_lower:
            return "other"
    
    # Strong invoice signals
    strong_invoice_signals = [
        "invoice", "tax invoice", "charge note", "billing statement",
        "tax document", "remittance notice", "receipt",
    ]
    
    # Moderate invoice signals
    moderate_invoice_signals = [
        "bill to", "ship to", "amount due", "total due",
        "payment terms", "grand total", "payable total", "total paid",
    ]
    
    # Structural signals
    has_reference = bool(re.search(r'(invoice|reference|ref|doc|document)\s*(no|number|#|id|ref)?[:\s]*[A-Z0-9-]+', text, re.IGNORECASE))
    has_customer = bool(re.search(r'(bill to|ship to|customer|client)[:\s]', text, re.IGNORECASE))
    has_subtotal = bool(re.search(r'subtotal|sub.?total|net\s*(charges|amount)', text, re.IGNORECASE))
    has_tax = bool(re.search(r'\b(vat|tax|gst|sales tax)\b', text, re.IGNORECASE))
    has_total = bool(re.search(r'(grand total|total due|amount due|payable total|total paid|total)[:\s]', text, re.IGNORECASE))
    
    score = 0
    
    for signal in strong_invoice_signals:
        if fuzzy_contains(text, signal, max_distance=2):
            score += 3
    
    for signal in moderate_invoice_signals:
        if fuzzy_contains(text, signal, max_distance=2):
            score += 2
    
    if has_reference:
        score += 2
    if has_customer:
        score += 2
    if has_subtotal:
        score += 1
    if has_tax:
        score += 1
    if has_total:
        score += 1
    
    if has_reference and has_customer and has_tax and has_total:
        score += 3
    
    return "invoice" if score >= 5 else "other"


# --- Amount Extraction ---

def parse_amount(amount_str: str):
    """Parse an amount string, handling commas, currency symbols, and European conventions."""
    cleaned = re.sub(r'[\$\u20ac\u00a3\u00a5\s]', '', amount_str)
    if re.match(r'^[\d.]+,\d{2}$', cleaned):
        cleaned = cleaned.replace('.', '').replace(',', '.')
    else:
        cleaned = cleaned.replace(',', '')
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_amount_after_label(text: str, label_pattern: str):
    """Find an amount that follows a label pattern in the text."""
    pattern = rf'{label_pattern}\s*:?\s*([\$\u20ac\u00a3]?\s*[\d,]+\.?\d*)'
    matches = re.findall(pattern, text, re.IGNORECASE)
    if matches:
        for match in reversed(matches):
            val = parse_amount(match)
            if val is not None and val > 0:
                return val
    return None


def extract_vat_from_context(all_texts: list, total_amount: float) -> float:
    """
    Extract VAT by looking for numbers with 2 decimal places on lines 
    between service items and total (the tax line even if garbled).
    """
    vat_candidates = []
    
    for text in all_texts:
        lines = text.split('\n')
        for i, line in enumerate(lines):
            line_lower = line.lower()
            # Look for total line
            if any(k in line_lower for k in ['total', 'due', 'paid']):
                # Look at 1-2 lines before total for tax amount
                for j in range(max(0, i-2), i):
                    m = re.findall(r'\d+\.\d{2}', lines[j])
                    if m:
                        for num_str in m:
                            val = float(num_str)
                            # VAT is usually < 30% of total
                            if val < total_amount * 0.3 and val > 0:
                                vat_candidates.append(val)
    
    if vat_candidates:
        # Return most common VAT candidate
        counter = Counter(vat_candidates)
        return counter.most_common(1)[0][0]
    
    return None


def extract_amounts_noisy_ocr(all_texts: list) -> dict:
    """
    Extract amounts from noisy OCR using frequency voting + arithmetic computation.
    """
    subtotal_vals = Counter()
    total_vals = Counter()
    vat_vals = Counter()
    
    for text in all_texts:
        for line in text.split('\n'):
            line_lower = line.lower()
            nums = re.findall(r'[\d,]+\.?\d*', line)
            if not nums:
                continue
            for n in nums:
                val = parse_amount(n)
                if val is None or val <= 0:
                    continue
                
                if any(k in line_lower for k in ['subtotal', 'subtot', 'subte', 'subto', 'subtest']):
                    subtotal_vals[val] += 1
                elif any(k in line_lower for k in ['vat', 'tax', 'gst', 'ast']):
                    vat_vals[val] += 1
                elif any(k in line_lower for k in ['total', 'paid', 'due', 'amount']):
                    if not any(k in line_lower for k in ['subtotal', 'subtot']):
                        total_vals[val] += 1
    
    # 1. Subtotal: pick most frequent (usually stable with decimals)
    best_subtotal = subtotal_vals.most_common(1)[0][0] if subtotal_vals else None
    
    # 2. Total: find value that makes arithmetic sense
    best_total = None
    if best_subtotal:
        for val, count in total_vals.most_common():
            # If val has no decimal and is > 100, try dividing by 100
            if val > 100 and val == int(val):
                candidate = val / 100.0
            else:
                candidate = val
            # Sanity check: total should be > subtotal but < 5x subtotal
            if candidate > best_subtotal and candidate < best_subtotal * 5:
                best_total = candidate
                break
        
        # Fallback: use most frequent total candidate with /100 if needed
        if best_total is None and total_vals:
            for val, count in total_vals.most_common():
                candidate = val / 100.0 if val > 100 else val
                best_total = candidate
                break
    
    # 3. VAT: try to extract clean X.XX from VAT lines, otherwise compute
    best_vat = None
    for text in all_texts:
        for line in text.split('\n'):
            line_lower = line.lower()
            if any(k in line_lower for k in ['vat', 'tax', 'gst', 'ast']):
                # Extract any number with 2 decimal places
                m = re.findall(r'\d+\.\d{2}', line)
                if m:
                    best_vat = float(m[-1])
    
    # If no clean VAT found, compute it
    if best_vat is None and best_total and best_subtotal:
        best_vat = round(best_total - best_subtotal, 2)
    
    return {"total_amount": best_total, "vat_amount": best_vat}


def extract_financial_amounts(text: str, all_texts: list = None) -> dict:
    """
    Extract total_amount and vat_amount from document text.
    Uses label-proximity for clean text, frequency voting for noisy OCR.
    """
    # Strategy 1: Label-based extraction (works for clean PDFs)
    result = {"total_amount": None, "vat_amount": None}
    
    total_labels = [
        r'(?:grand\s+total|amount\s+due|total\s+due|payable\s+total|balance\s+due|total\s+paid)',
        r'total',
    ]
    for label in total_labels:
        val = extract_amount_after_label(text, label)
        if val is not None:
            result["total_amount"] = val
            break
    
    vat_labels = [r'(?:vat|tax|gst|sales\s+tax)']
    for label in vat_labels:
        val = extract_amount_after_label(text, label)
        if val is not None:
            result["vat_amount"] = val
            break
    
    subtotal = extract_amount_after_label(text, r'subtotal|sub.?total|net\s*(?:charges|amount)')
    
    # Cross-validation with arithmetic
    if subtotal is not None and result["total_amount"] is not None:
        expected_vat = round(result["total_amount"] - subtotal, 2)
        if result["vat_amount"] is not None:
            if abs(result["vat_amount"] - expected_vat) > 0.5:
                result["vat_amount"] = expected_vat
        else:
            result["vat_amount"] = expected_vat
    
    # Strategy 2: For OCR-noisy documents with multiple texts
    if all_texts and len(all_texts) > 1:
        needs_retry = (result["total_amount"] is None or result["vat_amount"] is None)
        
        if needs_retry:
            ocr_result = extract_amounts_noisy_ocr(all_texts)
            if ocr_result["total_amount"] is not None and result["total_amount"] is None:
                result["total_amount"] = ocr_result["total_amount"]
            if ocr_result["vat_amount"] is not None and result["vat_amount"] is None:
                result["vat_amount"] = ocr_result["vat_amount"]
    
    # Strategy 3: Extract VAT from context (lines between service and total)
    if result["vat_amount"] is None and result["total_amount"] is not None and all_texts:
        vat_from_context = extract_vat_from_context(all_texts, result["total_amount"])
        if vat_from_context is not None:
            result["vat_amount"] = vat_from_context
    
    return result


# --- Main ---

def main():
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)
    
    extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.gif'}
    doc_files = sorted([
        f for f in DOCS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in extensions
    ])
    
    print(f"Found {len(doc_files)} documents to process.\n")
    
    invoices = []
    
    for doc_path in doc_files:
        print(f"Processing: {doc_path.name}")
        text, all_texts = extract_text(doc_path)
        print(f"  Extracted {len(text)} chars from {len(all_texts)} OCR variants")
        
        classification = classify_document(text)
        print(f"  Classification: {classification}")
        
        if classification == "invoice":
            amounts = extract_financial_amounts(text, all_texts)
            total = amounts["total_amount"]
            vat = amounts["vat_amount"]
            print(f"  Total: {total}, VAT: {vat}")
            
            if total is None:
                print(f"  WARNING: Could not extract total_amount!")
            if vat is None:
                print(f"  WARNING: Could not extract vat_amount!")
            
            invoices.append((doc_path.name, total, vat))
            shutil.move(str(doc_path), str(INVOICES_DIR / doc_path.name))
        else:
            shutil.move(str(doc_path), str(OTHER_DIR / doc_path.name))
        
        print()
    
    # Write summary.csv
    print(f"Writing summary.csv with {len(invoices)} invoices...")
    with open(SUMMARY_CSV, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])
        
        total_sum = 0.0
        vat_sum = 0.0
        
        for filename, total, vat in invoices:
            t = total if total is not None else 0.0
            v = vat if vat is not None else 0.0
            writer.writerow([filename, f"{t:.2f}", f"{v:.2f}"])
            total_sum += t
            vat_sum += v
        
        writer.writerow(['total', f"{total_sum:.2f}", f"{vat_sum:.2f}"])
    
    print(f"Summary totals: total_amount={total_sum:.2f}, vat_amount={vat_sum:.2f}")
    
    remaining = list(DOCS_DIR.iterdir())
    if remaining:
        print(f"WARNING: {len(remaining)} files remain in documents/")
    else:
        print("Verified: documents/ is empty.")
    
    print("\nDone!")


if __name__ == "__main__":
    main()
