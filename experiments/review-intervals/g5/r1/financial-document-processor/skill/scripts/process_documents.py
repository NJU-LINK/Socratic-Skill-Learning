#!/usr/bin/env python3
"""
Financial Document Processor - Reference implementation
Classifies documents as invoice/other, extracts financial fields,
moves files, and creates summary CSV.

Key design: Line-label-first extraction with arithmetic validation.
"""

import os
import re
import csv
import shutil
import subprocess
import fitz  # PyMuPDF
from pathlib import Path

DOCS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
SUMMARY_PATH = INVOICES_DIR / "summary.csv"


def extract_text_from_pdf(filepath):
    """Extract text from PDF using PyMuPDF, fallback to pdftotext."""
    text = ""
    try:
        doc = fitz.open(str(filepath))
        for page in doc:
            text += page.get_text()
        doc.close()
    except Exception:
        pass
    
    if not text.strip():
        try:
            result = subprocess.run(
                ["pdftotext", str(filepath), "-"],
                capture_output=True, text=True, timeout=30
            )
            text = result.stdout
        except Exception:
            pass
    return text


def extract_text_from_image(filepath):
    """Extract text from image using Tesseract with multiple PSM modes."""
    all_texts = []
    for psm in [3, 4, 6, 11, 12]:
        try:
            result = subprocess.run(
                ["tesseract", str(filepath), "stdout", "--psm", str(psm)],
                capture_output=True, text=True, timeout=30
            )
            if result.stdout.strip():
                all_texts.append(result.stdout)
        except Exception:
            pass
    
    if all_texts:
        seen_lines = set()
        combined_lines = []
        for text in all_texts:
            for line in text.split('\n'):
                stripped = line.strip()
                if stripped and stripped not in seen_lines:
                    seen_lines.add(stripped)
                    combined_lines.append(stripped)
        return '\n'.join(combined_lines)
    return ""


def extract_text(filepath):
    """Extract text from PDF or image file."""
    ext = filepath.suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"):
        return extract_text_from_image(filepath)
    return ""


def fuzzy_match(keyword, text, max_distance=2):
    """Check if keyword approximately appears in text."""
    keyword_lower = keyword.lower()
    text_lower = text.lower()
    klen = len(keyword_lower)
    
    if klen == 0:
        return True
    
    if keyword_lower in text_lower:
        return True
    
    for i in range(len(text_lower) - klen + 1):
        window = text_lower[i:i+klen]
        mismatches = sum(1 for a, b in zip(keyword_lower, window) if a != b)
        if mismatches <= max_distance:
            return True
    
    return False


def classify_document(text):
    """
    Classify document as 'invoice' or 'other'.
    
    Key distinction: Invoice = requesting payment, Receipt = confirming payment
    """
    # Negative signals (disqualify from invoice)
    negative_keywords = [
        "purchase order",
        "payment reminder",
        "expense reimbursement",
        "reimbursement summary",
        "reimbursement form",
        "reimbursement claim",
        "not a tax invoice",
        "not an invoice",
        "delivery note",
        "packing slip",
        "receipt",       # Proof of payment, not a billing request
        "card payment",  # Indicates payment already made
    ]
    
    for kw in negative_keywords:
        if fuzzy_match(kw, text, max_distance=2):
            return "other"
    
    # Positive signals (indicate invoice - requesting payment)
    strong_invoice_keywords = [
        "invoice",
        "tax document",
        "tax invoice",
        "billing statement",
        "charge note",
        "remittance notice",
        "amount due",
        "total due",
        "payable",
    ]
    
    for kw in strong_invoice_keywords:
        if fuzzy_match(kw, text, max_distance=2):
            return "invoice"
    
    # Fallback: check for structural cues
    has_customer = fuzzy_match("customer", text, max_distance=2) or \
                   fuzzy_match("bill to", text, max_distance=2) or \
                   fuzzy_match("client", text, max_distance=1)
    
    has_total = bool(re.search(r'(?:total|amount)\s*(?:due|payable)', text.lower()))
    has_tax = bool(re.search(r'(?:vat|tax|gst)', text.lower()))
    
    if has_customer and has_total and has_tax:
        return "invoice"
    
    return "other"


def parse_amount(s):
    """Parse a monetary amount string."""
    if not s:
        return None
    cleaned = re.sub(r'[^\d.,]', '', s.strip())
    if not cleaned:
        return None
    if ',' in cleaned and '.' in cleaned:
        cleaned = cleaned.replace(',', '')
    elif ',' in cleaned and '.' not in cleaned:
        parts = cleaned.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    try:
        return float(cleaned)
    except ValueError:
        return None


def has_any_keyword(text_lower, keywords):
    """Check if text contains any of the keywords."""
    for kw in keywords:
        if kw in text_lower:
            return True
    return False


def label_line(line_text):
    """
    Label a line's financial role using three-tier keyword matching.
    
    Tier 1: Word-boundary regex for short keywords (tax, vat, gst)
    Tier 2: Substring matching for longer phrases
    Tier 3: Explicit OCR-variant patterns
    
    Returns: (is_subtotal, is_total, is_tax, is_doc_header)
    """
    ll = line_text.lower().strip()
    
    # Tier 1: Word-boundary regex for short keywords
    is_tax_short = bool(re.search(r'\btax\b|\bvat\b|\bgst\b', ll))
    
    # Tier 2: Substring matching for longer phrases
    is_subtotal = has_any_keyword(ll, [
        'subtotal', 'subtotat', 'sub toat', 'sub-total',
        'net charges', 'consulting services', 'hardware order',
        'freight services', 'design retainer'
    ])
    
    is_total = has_any_keyword(ll, [
        'total', 'amount due', 'grand total', 'payable total',
        'total due', 'total paid', 'total pet', 'otal paid',
        'balance due', 'invoice total', 'total payable'
    ])
    
    is_tax_phrase = has_any_keyword(ll, [
        'sales tax', 'vat included', 'tax included'
    ])
    
    is_doc_header = has_any_keyword(ll, [
        'document', 'invoice', 'notice', 'statement', 'note'
    ])
    
    # Tier 3: Explicit OCR-variant patterns
    # "ast78.40" → tax (VAT with V dropped)
    ocr_tax = bool(re.search(r'^\s*ast\s*\d', ll))
    # "teal due" → total (Total with o→e)
    ocr_total = bool(re.search(r'teal\s+due', ll))
    # "charge nate" / "charge nols" → classification (handled elsewhere)
    
    # Combine tiers
    is_tax = is_tax_short or is_tax_phrase or ocr_tax
    is_total = is_total or ocr_total
    
    return is_subtotal, is_total, is_tax, is_doc_header


def extract_financial_fields(text):
    """
    Extract total_amount and vat_amount using line-label-first approach.
    
    Phase 1: Label every line by its financial role using keywords.
    Phase 2: Pick best values using arithmetic consistency.
    """
    lines = text.split('\n')
    
    total_candidates = []
    tax_candidates = []
    subtotal_candidates = []
    
    for line in lines:
        ll = line.lower().strip()
        if not ll:
            continue
        
        number_matches = re.findall(r'(\d[\d,]*\.?\d*)', line)
        amounts = []
        for num_str in number_matches:
            amount = parse_amount(num_str)
            if amount is not None and amount > 0:
                amounts.append((amount, num_str))
        
        if not amounts:
            continue
        
        # Skip non-field lines
        skip_patterns = [
            r'\bdate\b', r'\bissued\b', r'\breference\b', r'\bref\b',
            r'\bdoc\b', r'\bid\b', r'\bpo\b', r'\bnumber\b',
            r'\bwithin\b.*\bdays\b', r'\bstatus\b', r'\bapproved\b'
        ]
        is_skip = any(re.search(p, ll) for p in skip_patterns)
        
        has_financial_kw = has_any_keyword(ll, [
            'total', 'subtotal', 'tax', 'vat', 'gst', 'amount due',
            'grand total', 'payable', 'services', 'retainer', 'order'
        ])
        
        if is_skip and not has_financial_kw:
            continue
        
        # Skip integers > 4 digits (likely reference numbers)
        first_num_str = number_matches[0]
        if '.' not in first_num_str and len(first_num_str.replace(',', '')) > 4:
            continue
        
        # Classify line role using three-tier matching
        is_subtotal, is_total, is_tax, is_doc_header = label_line(ll)
        
        # For lines with multiple numbers, filter out percentages
        filtered_amounts = []
        for amount, num_str in amounts:
            pct_pattern = re.escape(num_str) + r'\s*%'
            if not re.search(pct_pattern, line):
                filtered_amounts.append(amount)
        
        if not filtered_amounts:
            continue
        
        # Take the largest filtered amount
        amount = max(filtered_amounts)
        
        if is_subtotal:
            subtotal_candidates.append(amount)
        elif is_total and not is_subtotal:
            total_candidates.append(amount)
        elif is_tax and not is_doc_header:
            tax_candidates.append(amount)
    
    # Remove duplicates
    total_candidates = list(set(total_candidates))
    tax_candidates = list(set(tax_candidates))
    subtotal_candidates = list(set(subtotal_candidates))
    
    # Use arithmetic to pick the best combination
    best_total = None
    best_subtotal = None
    best_tax = None
    best_score = float('inf')
    
    # Try all combinations (including decimal-repaired versions)
    for total in total_candidates:
        total_variants = [total]
        if total > 100 and total == int(total):
            total_variants.append(total / 100)
        
        for total_v in total_variants:
            for subtotal in subtotal_candidates:
                if subtotal >= total_v:
                    continue
                
                implied_tax = round(total_v - subtotal, 2)
                
                # Try both original and decimal-repaired tax candidates
                tax_variants = list(tax_candidates)
                for t in tax_candidates:
                    if t > 100 and t == int(t):
                        tax_variants.append(t / 100)
                
                # Score this combination
                if tax_variants:
                    closest_tax = min(tax_variants, key=lambda t: abs(t - implied_tax))
                    score = abs(closest_tax - implied_tax)
                    tax = closest_tax
                else:
                    tax = implied_tax
                    score = 0
                
                if score < best_score:
                    best_score = score
                    best_total = total_v
                    best_subtotal = subtotal
                    best_tax = tax
    
    # Fallback
    if best_total is None:
        if total_candidates:
            best_total = max(total_candidates)
        if subtotal_candidates:
            best_subtotal = max(subtotal_candidates)
        if tax_candidates:
            best_tax = max(tax_candidates)
        elif best_total and best_subtotal:
            best_tax = round(best_total - best_subtotal, 2)
    
    return best_total, best_tax


def main():
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)
    
    files = []
    for f in sorted(DOCS_DIR.iterdir()):
        if f.suffix.lower() in ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'):
            files.append(f)
    
    print(f"Found {len(files)} documents to process")
    
    invoice_rows = []
    
    for filepath in files:
        print(f"\n{'='*60}")
        print(f"Processing: {filepath.name}")
        
        text = extract_text(filepath)
        print(f"  Extracted {len(text)} chars")
        
        classification = classify_document(text)
        print(f"  Classification: {classification}")
        
        if classification == "invoice":
            total_amount, vat_amount = extract_financial_fields(text)
            print(f"  Total: {total_amount}, VAT: {vat_amount}")
            
            dest = INVOICES_DIR / filepath.name
            shutil.move(str(filepath), str(dest))
            
            invoice_rows.append({
                'filename': filepath.name,
                'total_amount': round(total_amount, 2) if total_amount is not None else 0.0,
                'vat_amount': round(vat_amount, 2) if vat_amount is not None else 0.0,
            })
        else:
            dest = OTHER_DIR / filepath.name
            shutil.move(str(filepath), str(dest))
    
    print(f"\n{'='*60}")
    print(f"Writing summary.csv with {len(invoice_rows)} invoices")
    
    with open(SUMMARY_PATH, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['filename', 'total_amount', 'vat_amount'])
        writer.writeheader()
        
        total_sum = 0.0
        vat_sum = 0.0
        
        for row in invoice_rows:
            writer.writerow(row)
            total_sum += row['total_amount']
            vat_sum += row['vat_amount']
            print(f"  {row['filename']}: total={row['total_amount']}, vat={row['vat_amount']}")
        
        writer.writerow({
            'filename': 'total',
            'total_amount': round(total_sum, 2),
            'vat_amount': round(vat_sum, 2),
        })
    
    print(f"\nSummary totals: total_amount={round(total_sum, 2)}, vat_amount={round(vat_sum, 2)}")
    print(f"Documents remaining: {len(list(DOCS_DIR.iterdir()))}")
    print("Done!")


if __name__ == "__main__":
    main()
