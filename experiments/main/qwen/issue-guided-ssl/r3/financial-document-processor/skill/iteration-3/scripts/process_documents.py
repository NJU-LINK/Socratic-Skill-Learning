#!/usr/bin/env python3
"""
Financial Document Processor
Classifies mixed PDF/JPG documents as invoice or other,
routes them to appropriate directories, and generates summary CSV.

Architecture:
- Classification uses COMBINED text from all PSM modes (more signals = better)
- Amount extraction for OCR uses PER-PSM independent extraction with
  mathematical consistency scoring (avoids contradictory readings)
- Amount extraction for PDFs uses clean text directly
"""

import os
import re
import csv
import shutil
import subprocess
import sys
from pathlib import Path


# === Configuration ===
DOCUMENTS_DIR = "/app/documents"
INVOICES_DIR = "/app/invoices"
OTHER_DIR = "/app/other"
SUMMARY_CSV = os.path.join(INVOICES_DIR, "summary.csv")


# === Text Extraction ===

def extract_text_from_pdf(filepath):
    """Extract text from PDF using pdftotext."""
    try:
        result = subprocess.run(
            ["pdftotext", filepath, "-"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"  Warning: PDF extraction failed for {filepath}: {e}")
        return ""


def extract_text_from_jpg(filepath):
    """Extract combined text from JPG using multiple PSM modes.
    Used for CLASSIFICATION (more signals = better)."""
    try:
        from PIL import Image
        import pytesseract
        
        img = Image.open(filepath)
        texts = []
        for psm in [4, 6, 3, 11]:
            try:
                text = pytesseract.image_to_string(img, config=f'--psm {psm}')
                texts.append(text)
            except Exception:
                pass
        
        combined = "\n".join(texts)
        return combined.strip()
    except Exception as e:
        print(f"  Warning: OCR failed for {filepath}: {e}")
        return ""


def extract_text_per_psm(filepath):
    """Extract text from JPG per PSM mode for independent amount extraction.
    Returns dict of {psm_mode: text}. Each PSM reading is evaluated independently
    to avoid contradictory readings from different OCR modes."""
    try:
        from PIL import Image
        import pytesseract
        
        img = Image.open(filepath)
        results = {}
        for psm in [4, 6, 3, 11]:
            try:
                text = pytesseract.image_to_string(img, config=f'--psm {psm}')
                if text.strip():
                    results[psm] = text.strip()
            except Exception:
                pass
        return results
    except Exception as e:
        print(f"  Warning: OCR failed for {filepath}: {e}")
        return {}


def extract_text(filepath):
    """Extract text from a document file based on extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        return extract_text_from_jpg(filepath)
    else:
        print(f"  Warning: Unsupported file type: {ext}")
        return ""


# === OCR-tolerant pattern matching ===

def _build_fuzzy_pattern(pattern):
    """Build a fuzzy regex pattern from an exact pattern.
    Replaces each literal character with a character class of its OCR confusions.
    Only replaces literal characters, not regex metacharacters or existing classes."""
    # Map each letter to its OCR-confusable character class
    char_map = {
        'p': '[pb]', 'b': '[pb]',
        'c': '[ce]', 'e': '[ea3]',
        'i': '[il1!]', 'l': '[l1i!]',
        'o': '[0oa]', 'a': '[a4@]',
        's': '[sz$5]', 't': '[t+7]',
        'n': '[nr]', 'r': '[rn]',
        'd': '[dcl]', 'v': '[vu]',
        'f': '[ft]', 'g': '[gq9]',
        'h': '[h]', 'j': '[j]',
        'k': '[k]', 'm': '[mn]',
        'q': '[qg]', 'w': '[w]',
        'x': '[x]', 'y': '[y]',
        'z': '[zs2]',
    }
    
    result = []
    in_class = False
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        
        # Handle escape sequences
        if ch == '\\' and i + 1 < len(pattern):
            result.append(pattern[i:i+2])
            i += 2
            continue
        
        # Handle character classes [...] - pass through unchanged
        if ch == '[':
            in_class = True
            result.append(ch)
            i += 1
            continue
        if ch == ']' and in_class:
            in_class = False
            result.append(ch)
            i += 1
            continue
        if in_class:
            result.append(ch)
            i += 1
            continue
        
        # Handle other regex metacharacters - pass through unchanged
        if ch in r'(){}|.^$*+?':
            result.append(ch)
            i += 1
            continue
        
        # Replace literal lowercase letter with its confusion class
        lower_ch = ch.lower()
        if lower_ch in char_map:
            result.append(char_map[lower_ch])
        else:
            result.append(ch)
        i += 1
    
    return ''.join(result)


def ocr_fuzzy_match(text, patterns):
    """Match patterns with tolerance for OCR errors.
    Handles common OCR character confusions by building per-character
    character classes from a confusion map."""
    text_lower = text.lower()
    matches = 0
    
    for pattern in patterns:
        if re.search(pattern, text_lower):
            matches += 1
            continue
        
        # Build fuzzy pattern character-by-character
        fuzzy_pattern = _build_fuzzy_pattern(pattern)
        
        try:
            if re.search(fuzzy_pattern, text_lower):
                matches += 1
        except re.error:
            pass
    
    return matches


# === Classification ===

PRO_INVOICE_PATTERNS = [
    # Document type headers (formal billing documents)
    r'\binvoice\b', r'\btax\s+invoice\b', r'\btax\s+document\b',
    r'\bbilling\s+statement\b', r'\bbill\b', r'\bremittance\s+notice\b',
    r'\bcharge\s+note\b', r'\bcharge\s+invoice\b', r'\bsales\s+invoice\b',
    # Final-amount labels (structured invoice totals)
    r'\bgrand\s+total\b', r'\bamount\s+due\b', r'\btotal\s+due\b',
    r'\bpayable\s+total\b', r'\bbalance\s+due\b', r'\btotal\s+payable\b',
    r'\btotal\s+amount\b',
    # Tax indicators
    r'\bvat\b', r'\bgst\b', r'\bsales\s+tax\b',
    # Transaction context (formal billing relationships)
    r'\bcustomer\b', r'\bclient\b', r'\bvendor\b',
    r'\bship\s+to\b', r'\bbill\s+to\b',
]

ANTI_INVOICE_PATTERNS = [
    r'not\s+(?:a\s+)?(?:tax\s+)?invoice',
    r'this\s+(?:document|notice|statement)\s+is\s+not',
    r'\bpurchase\s+order\b', r'\bquote\b', r'\bestimate\b',
    r'\bpro\s+forma\b', r'\bproposal\b',
    r'\bapproval\s+status\s*:\s*pending\b', r'\bdraft\b',
    r'\brequested\b', r'\bestimated\b', r'\bapproved\s+spend\s+ceiling\b',
    r'\bpayment\s+reminder\b', r'\bdunning\s+letter\b',
    r'\bstatement\s+of\s+account\b', r'\boutstanding\s+balance\b',
    r'\bthis\s+notice\b',
    r'\bexpense\s+reimbursement\b', r'\breimbursement\s+summary\b',
    r'\breclaimable\b', r'\bapproved\s+meals\b',
    # Receipt/payment confirmation signals (NOT invoices)
    r'\breceipt\b', r'\bpayment\s+approved\b', r'\bcard\s+payment\b',
]


def classify_document(text):
    """Classify document as invoice or other using multi-signal scoring.
    Uses combined text from all PSM modes for maximum signal capture."""
    text_lower = text.lower()
    
    # Explicit disclaimers are decisive
    if re.search(r'not\s+(?:a\s+)?(?:tax\s+)?invoice', text_lower):
        return False
    if re.search(r'this\s+(?:document|notice|statement)\s+is\s+not', text_lower):
        return False
    
    pro_score = ocr_fuzzy_match(text, PRO_INVOICE_PATTERNS)
    
    anti_score = 0
    for pattern in ANTI_INVOICE_PATTERNS:
        if re.search(pattern, text_lower):
            anti_score += 1
    
    anti_weighted = anti_score * 2
    
    if anti_weighted >= 4:
        return False
    
    # Require at least 3 pro-invoice signals to classify as invoice
    # This prevents receipts and other documents with few genuine invoice
    # signals from being misclassified
    if pro_score >= 3 and pro_score > anti_weighted:
        return True
    
    return False


# === Amount Extraction ===

def parse_amount(amount_str):
    """Parse a monetary amount string to float."""
    if not amount_str:
        return None
    cleaned = re.sub(r'[^\d.,]', '', amount_str.strip())
    if not cleaned:
        return None
    
    if ',' in cleaned and '.' in cleaned:
        last_comma = cleaned.rfind(',')
        last_period = cleaned.rfind('.')
        if last_comma > last_period:
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        parts = cleaned.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_amounts_from_text(text):
    """
    Extract total_amount, vat_amount, and subtotal_amount from a single text string.
    Returns (total, vat, subtotal) tuple.
    
    This is the core extraction logic used by both PDF and OCR paths.
    """
    # Extract all numbers (with and without decimals)
    amounts_with_decimals = re.findall(r'(\d{1,3}(?:,\d{3})*\.\d{2})', text)
    amounts_without_decimals = re.findall(r'(?<!\d)(\d{3,5})(?!\.\d)', text)
    
    all_labeled_amounts = [parse_amount(a) for a in amounts_with_decimals]
    all_labeled_amounts = [a for a in all_labeled_amounts if a and a > 0]
    
    all_raw_numbers = []
    for a in amounts_without_decimals:
        try:
            num = int(a)
            all_raw_numbers.append(num)
        except:
            pass
    
    # Patterns for labeled amounts
    total_patterns = [
        r'(?:grand\s+total|amount\s+due|total\s+due|payable\s+total|balance\s+due|total\s+payable|total\s+paid|total\s+amount)[:\s]*[\$€£]?\s*([\d][\d,]*\.\d{2})',
        r'(?:total)[:\s]*[\$€£]?\s*([\d][\d,]*\.\d{2})',
    ]
    
    vat_patterns = [
        # Handle "VAT 10%: 128.00" format - percentage must be consumed before capturing amount
        r'(?:vat|gst|sales\s+tax|tax|ast)[:\s]*\d+%[:\s]*[\$€£]?\s*([\d][\d,]*\.?\d*)',
        # Handle "VAT: 128.00" or "VAT 128.00" format (must have decimal point to avoid matching tax rates)
        r'(?:vat|gst|sales\s+tax|tax|ast)[:\s]*[\$€£]?\s*([\d][\d,]*\.\d{2})',
        # Handle "VAT included 4.83" format (OCR noisy, must have decimal point)
        r'(?:vat|gst|sales\s+tax|tax|ast)\s+(?:included|rate)?[:\s]*[\$€£]?\s*([\d][\d,]*\.\d{2})',
    ]
    
    # Tax rate patterns (for computing VAT when amount not explicit)
    tax_rate_patterns = [
        r'(?:vat|gst|sales\s+tax|tax|ast)[:\s]*(\d+(?:\.\d+)?)%',
        r'(\d+(?:\.\d+)?)%\s*(?:vat|gst|sales\s+tax|tax)',
    ]
    
    subtotal_patterns = [
        r'(?:subtotal|sub\s*total|net\s+charges|net\s+amount|subtott|subtest)[:\s]*[\$€£]?\s*([\d][\d,]*\.\d{2})',
    ]
    
    total_amount = None
    vat_amount = None
    subtotal_amount = None
    
    # Extract subtotal first (needed for VAT validation)
    for pattern in subtotal_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            amount = parse_amount(matches[0].group(1))
            if amount:
                subtotal_amount = amount
                break
    
    # Extract total
    for pattern in total_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            amount = parse_amount(matches[-1].group(1))
            if amount:
                total_amount = amount
                break
    
    # Extract VAT
    for pattern in vat_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            amount_str = matches[0].group(1)
            amount = parse_amount(amount_str)
            if amount:
                # Only apply /100 correction if amount has no decimal point
                # (indicates OCR noise like "483" instead of "4.83")
                # If amount already has decimal places, it's likely correct
                if '.' not in amount_str and amount > 100 and subtotal_amount:
                    adjusted = amount / 100
                    if adjusted < subtotal_amount * 0.3:
                        vat_amount = adjusted
                    else:
                        vat_amount = amount
                else:
                    vat_amount = amount
                break
    
    # Re-extract VAT with subtotal known if not found
    if subtotal_amount and vat_amount is None:
        for pattern in vat_patterns:
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            if matches:
                amount_str = matches[0].group(1)
                amount = parse_amount(amount_str)
                if amount:
                    # Only apply /100 correction if no decimal point
                    if '.' not in amount_str and amount > 100:
                        adjusted = amount / 100
                        if adjusted < subtotal_amount * 0.3:
                            vat_amount = adjusted
                        else:
                            vat_amount = amount
                    else:
                        vat_amount = amount
                    break
    
    # Mathematical consistency checks
    if subtotal_amount and vat_amount and total_amount:
        expected_total = round(subtotal_amount + vat_amount, 2)
        if abs(expected_total - total_amount) > 0.10:
            for raw_num in all_raw_numbers:
                adjusted = raw_num / 100
                if abs(adjusted - expected_total) < 0.10:
                    total_amount = adjusted
                    break
    
    # Compute missing values from mathematical relationships
    if total_amount is None and subtotal_amount and vat_amount:
        total_amount = round(subtotal_amount + vat_amount, 2)
    
    if vat_amount is None and total_amount and subtotal_amount:
        vat_amount = round(total_amount - subtotal_amount, 2)
    
    # If VAT still not found, try to extract tax rate and compute from subtotal
    if vat_amount is None and subtotal_amount:
        tax_rate = None
        for pattern in tax_rate_patterns:
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            if matches:
                try:
                    tax_rate = float(matches[0].group(1))
                    break
                except (ValueError, IndexError):
                    pass
        
        # Compute VAT from rate if found
        if tax_rate is not None and 0 < tax_rate <= 100:
            computed_vat = round(subtotal_amount * tax_rate / 100, 2)
            # Validate against total if available
            if total_amount:
                expected_total = round(subtotal_amount + computed_vat, 2)
                if abs(expected_total - total_amount) < 0.10:
                    vat_amount = computed_vat
            else:
                # No total to validate against, use computed value
                vat_amount = computed_vat
                # Also compute total
                total_amount = round(subtotal_amount + vat_amount, 2)
    
    # Fallback: use largest amount as total
    if total_amount is None and all_labeled_amounts:
        total_amount = max(all_labeled_amounts)
    
    if vat_amount is None and subtotal_amount and total_amount:
        vat_amount = round(total_amount - subtotal_amount, 2)
    
    return total_amount, vat_amount, subtotal_amount


def extract_amounts_ocr(filepath):
    """
    For OCR documents: extract amounts per-PSM independently, then select
    the result with best mathematical consistency (subtotal + VAT ≈ total).
    
    This avoids the problem where different PSM modes produce contradictory
    readings of the same field, and last-match-wins is arbitrary.
    
    Returns (total_amount, vat_amount) tuple.
    """
    psm_texts = extract_text_per_psm(filepath)
    
    if not psm_texts:
        return None, None
    
    candidates = []
    
    for psm, text in psm_texts.items():
        total, vat, subtotal = extract_amounts_from_text(text)
        
        if total is not None:
            # Score by mathematical consistency
            score = 0
            if subtotal and vat:
                expected_total = round(subtotal + vat, 2)
                if abs(expected_total - total) < 0.10:
                    score = 3  # Perfect consistency
                else:
                    score = 1  # Partial (have all three but inconsistent)
            elif total:
                score = 0  # Only total found
            
            candidates.append((score, total, vat, subtotal, psm))
    
    if not candidates:
        return None, None
    
    # Pick the most consistent result
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0]
    
    total_amount = best[1]
    vat_amount = best[2] if best[2] is not None else 0.0
    
    return total_amount, vat_amount


def extract_amounts(text):
    """
    Extract total_amount and vat_amount from clean text (PDFs).
    Wrapper around extract_amounts_from_text.
    """
    total, vat, subtotal = extract_amounts_from_text(text)
    return total, vat if vat is not None else 0.0


# === Main Processing Pipeline ===

def process_documents():
    """Main processing pipeline."""
    os.makedirs(INVOICES_DIR, exist_ok=True)
    os.makedirs(OTHER_DIR, exist_ok=True)
    
    doc_files = []
    for f in os.listdir(DOCUMENTS_DIR):
        filepath = os.path.join(DOCUMENTS_DIR, f)
        if os.path.isfile(filepath):
            ext = os.path.splitext(f)[1].lower()
            if ext in ('.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.bmp'):
                doc_files.append((f, filepath))
    
    doc_files.sort()
    invoices = []
    
    print(f"Found {len(doc_files)} documents to process")
    
    for filename, filepath in doc_files:
        print(f"\nProcessing: {filename}")
        
        # Extract combined text for classification (more signals = better)
        text = extract_text(filepath)
        print(f"  Extracted {len(text)} characters")
        
        if not text:
            print(f"  Warning: No text extracted, classifying as 'other'")
            dest = os.path.join(OTHER_DIR, filename)
            shutil.move(filepath, dest)
            continue
        
        # Classification uses combined text
        is_invoice = classify_document(text)
        print(f"  Classification: {'invoice' if is_invoice else 'other'}")
        
        if is_invoice:
            # Amount extraction: per-PSM for OCR, direct for PDF
            ext = os.path.splitext(filepath)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp'):
                # For OCR: extract amounts per-PSM, pick most consistent
                total_amount, vat_amount = extract_amounts_ocr(filepath)
            else:
                # For PDF: text is clean, use direct extraction
                total_amount, vat_amount = extract_amounts(text)
            
            print(f"  Total: {total_amount}, VAT: {vat_amount}")
            
            if total_amount is None:
                print(f"  Warning: Could not extract total amount")
                total_amount = 0.0
            if vat_amount is None:
                print(f"  Warning: Could not extract VAT amount")
                vat_amount = 0.0
            
            invoices.append((filename, total_amount, vat_amount))
            dest = os.path.join(INVOICES_DIR, filename)
            shutil.move(filepath, dest)
        else:
            dest = os.path.join(OTHER_DIR, filename)
            shutil.move(filepath, dest)
    
    print(f"\nWriting summary CSV with {len(invoices)} invoices")
    
    with open(SUMMARY_CSV, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])
        
        total_sum = 0.0
        vat_sum = 0.0
        
        for filename, total_amount, vat_amount in invoices:
            writer.writerow([filename, f"{total_amount:.2f}", f"{vat_amount:.2f}"])
            total_sum += total_amount
            vat_sum += vat_amount
        
        writer.writerow(['total', f"{total_sum:.2f}", f"{vat_sum:.2f}"])
    
    print(f"Summary: total_amount={total_sum:.2f}, vat_amount={vat_sum:.2f}")
    
    remaining = os.listdir(DOCUMENTS_DIR)
    if remaining:
        print(f"Warning: {len(remaining)} files remain in documents directory")
    else:
        print("Documents directory is empty. Processing complete.")
    
    return invoices


if __name__ == "__main__":
    process_documents()
