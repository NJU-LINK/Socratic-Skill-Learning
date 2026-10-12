#!/usr/bin/env python3
"""
Financial Document Processor - Reusable skill for classifying and extracting
data from mixed batches of financial documents (PDFs and images).

Handles:
- Invoice vs non-invoice classification via structural financial patterns
- Amount extraction with arithmetic cross-validation (subtotal + tax ≈ total)
- Noisy OCR from images via multi-PSM, multi-preprocessing extraction
- Variable batch sizes and document mixes
"""

import os
import sys
import re
import csv
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Try imports with fallbacks
try:
    import pytesseract
    from PIL import Image, ImageFilter, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False


def extract_text_from_pdf(filepath: str) -> str:
    """Extract text from PDF using pdftotext (most reliable for text-based PDFs)."""
    try:
        result = subprocess.run(
            ['pdftotext', filepath, '-'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception:
        pass
    
    # Fallback to PyMuPDF
    if HAS_FITZ:
        try:
            doc = fitz.open(filepath)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            if text.strip():
                return text
        except Exception:
            pass
    
    # Last resort: render PDF pages as images and OCR
    if HAS_FITZ and HAS_PIL:
        try:
            doc = fitz.open(filepath)
            text = ""
            for page in doc:
                pix = page.get_pixmap(dpi=300)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text += pytesseract.image_to_string(img, config='--psm 6')
            doc.close()
            if text.strip():
                return text
        except Exception:
            pass
    
    return ""


def extract_text_from_image(filepath: str) -> str:
    """Extract text from image using multiple OCR strategies and combine results."""
    if not HAS_PIL:
        # Fallback to tesseract CLI
        try:
            result = subprocess.run(
                ['tesseract', filepath, 'stdout', '--psm', '6'],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout if result.returncode == 0 else ""
        except Exception:
            return ""
    
    img = Image.open(filepath)
    all_texts = []
    
    # Multiple preprocessing strategies
    preprocessors = {
        'original': img,
        'grayscale': img.convert('L'),
        'resized_2x': img.resize((img.width * 2, img.height * 2), Image.LANCZOS),
        'resized_gray_2x': img.convert('L').resize((img.width * 2, img.height * 2), Image.LANCZOS),
    }
    
    # Try sharpening on grayscale
    try:
        gray = img.convert('L')
        preprocessors['sharp_gray'] = gray.filter(ImageFilter.SHARPEN)
    except Exception:
        pass
    
    # Multiple PSM modes
    psm_modes = [3, 4, 6, 11, 12]
    
    for prep_name, prep_img in preprocessors.items():
        for psm in psm_modes:
            try:
                text = pytesseract.image_to_string(
                    prep_img, 
                    config=f'--psm {psm}'
                )
                if text.strip():
                    all_texts.append(text)
            except Exception:
                pass
    
    # Return the concatenation of all reads - the extraction logic will
    # handle finding the correct numbers via arithmetic cross-validation
    return "\n---\n".join(all_texts)


def extract_text(filepath: str) -> str:
    """Extract text from a document file (PDF or image)."""
    ext = Path(filepath).suffix.lower()
    if ext == '.pdf':
        return extract_text_from_pdf(filepath)
    elif ext in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.gif', '.webp'):
        return extract_text_from_image(filepath)
    return ""


def expand_decimal_candidates(integer_numbers: List[float]) -> List[float]:
    """Generate decimal-shifted candidates for OCR decimal recovery.
    
    OCR commonly drops decimal points: 4.83 → 483, 54.20 → 5420.
    This generates /10, /100, /1000 variants for integers so arithmetic 
    cross-validation can find the correct interpretation.
    
    Only expands integer numbers (those without decimal points in original text).
    """
    candidates = set()
    for n in integer_numbers:
        if n >= 100:  # Only expand large integers (likely missing decimal)
            candidates.add(n / 10)    # 483 → 48.3
            candidates.add(n / 100)   # 483 → 4.83
            candidates.add(n / 1000)  # 4830 → 4.830
    return sorted(candidates)


def extract_all_numbers(text: str) -> Tuple[List[float], List[float]]:
    """Extract all monetary-like numbers from text.
    
    Returns:
        Tuple of (decimal_numbers, integer_numbers)
        - decimal_numbers: numbers that had decimal points in original text
        - integer_numbers: numbers that were integers (no decimal point)
    """
    # Single comprehensive pattern that captures all number formats
    # Group 1: number with comma separators and decimal (1,234.56)
    # Group 2: number with decimal (1234.56)
    # Group 3: number with comma separators, no decimal (1,234)
    # Group 4: plain integer (1234)
    pattern = r'(\d{1,3}(?:,\d{3})*\.\d{1,2})|(\d+\.\d{1,2})|(\d{1,3}(?:,\d{3})+)|(\d{2,})'
    
    decimal_numbers = set()
    integer_numbers = set()
    
    for match in re.finditer(pattern, text):
        # Determine which group matched
        groups = match.groups()
        
        # Groups 1 and 2 have decimal points
        if groups[0] is not None or groups[1] is not None:
            num_str = groups[0] if groups[0] else groups[1]
            num_str = num_str.replace(',', '')
            try:
                val = float(num_str)
                if val > 0:
                    decimal_numbers.add(val)
            except ValueError:
                pass
        # Groups 3 and 4 are integers (no decimal point)
        elif groups[2] is not None or groups[3] is not None:
            num_str = groups[2] if groups[2] else groups[3]
            num_str = num_str.replace(',', '')
            try:
                val = float(num_str)
                if val > 0:
                    integer_numbers.add(val)
            except ValueError:
                pass
    
    return sorted(decimal_numbers), sorted(integer_numbers)


def find_tax_rates(text: str) -> List[float]:
    """Find tax rate percentages mentioned in the text.
    
    Looks for patterns like 'VAT 20%', 'GST 10%', 'Tax Rate: 8%', 'VAT at 15%'.
    Returns list of rate percentages found (e.g., [20.0, 10.0]).
    """
    rates = []
    # Match patterns like: VAT 20%, Tax Rate: 10%, GST at 8%, etc.
    rate_pattern = r'(?:vat|tax|gst|hst|sales\s*tax)\s*(?:rate)?\s*(?::|at)?\s*(\d+(?:\.\d+)?)\s*%'
    for match in re.finditer(rate_pattern, text, re.IGNORECASE):
        try:
            rate = float(match.group(1))
            if 0 < rate <= 100:  # Reasonable tax rate range
                rates.append(rate)
        except ValueError:
            pass
    return rates


def find_labeled_amounts(text: str) -> Dict[str, Tuple[List[float], List[float]]]:
    """Find amounts associated with specific labels in the text.
    
    Returns dict with keys 'subtotal', 'tax', 'total', 'net', each containing
    a tuple of (decimal_numbers, integer_numbers).
    """
    results = {
        'subtotal': ([], []),
        'tax': ([], []),
        'total': ([], []),
        'net': ([], []),
    }
    
    lines = text.split('\n')
    
    # Patterns for different field types
    subtotal_patterns = [
        r'sub\s*total', r'subtot', r'subt[oe][st]',  # catches Subtott, Subtest (OCR noise)
        r'net\s*(?:charge|amount|price)',
        r'(?:design|freight|consulting|hardware|service)s?\s*(?:retainer|charge|cost)?'
    ]
    tax_patterns = [
        r'vat', r'tax', r'gst', r'sales\s*tax', r'hst'
    ]
    total_patterns = [
        r'(?:grand\s*)?total', r'amount\s*due', r'total\s*due',
        r'payable\s*total', r'total\s*paid', r'balance\s*due',
        r'outstanding\s*balance', r'total\s*this\s*week'
    ]
    net_patterns = [
        r'net\s*charges?', r'net\s*amount'
    ]
    
    for line in lines:
        line_lower = line.lower()
        # Extract numbers from this line
        decimal_nums, integer_nums = extract_all_numbers(line)
        if not decimal_nums and not integer_nums:
            continue
        
        # Skip lines that are purely tax rate expressions (e.g., "VAT Rate: 20%")
        # These contain a percentage, not a monetary amount
        if re.search(r'\d+(?:\.\d+)?\s*%', line):
            # If the line has a percentage AND a monetary amount, still process it
            # But if the only number is the percentage, skip it as a tax amount
            has_monetary = any(
                re.search(r'\d{1,3}(?:,\d{3})*\.\d{2}', line) or
                re.search(r'\d+\.\d{2}', line)
                for _ in [1]
            )
            if not has_monetary:
                continue
        
        for pat in subtotal_patterns:
            if re.search(pat, line_lower):
                results['subtotal'] = (
                    results['subtotal'][0] + decimal_nums,
                    results['subtotal'][1] + integer_nums
                )
                break
        for pat in tax_patterns:
            if re.search(pat, line_lower):
                results['tax'] = (
                    results['tax'][0] + decimal_nums,
                    results['tax'][1] + integer_nums
                )
                break
        for pat in total_patterns:
            if re.search(pat, line_lower):
                results['total'] = (
                    results['total'][0] + decimal_nums,
                    results['total'][1] + integer_nums
                )
                break
        for pat in net_patterns:
            if re.search(pat, line_lower):
                results['net'] = (
                    results['net'][0] + decimal_nums,
                    results['net'][1] + integer_nums
                )
                break
    
    # Deduplicate
    for key in results:
        dec, ints = results[key]
        results[key] = (sorted(set(dec)), sorted(set(ints)))
    
    return results


def arithmetic_cross_validate(labeled: Dict[str, Tuple[List[float], List[float]]], 
                               decimal_numbers: List[float],
                               integer_numbers: List[float],
                               text: str = "") -> Optional[Tuple[float, float]]:
    """
    Use the arithmetic identity subtotal + tax = total to find the correct
    total_amount and vat_amount from candidate values.
    
    Returns (total_amount, vat_amount) or None if no valid combination found.
    """
    # Build candidate lists: decimal numbers + expanded integers
    expanded_integers = expand_decimal_candidates(integer_numbers)
    all_candidates = sorted(set(decimal_numbers + expanded_integers))
    
    # Build labeled candidates
    totals_dec, totals_int = labeled.get('total', ([], []))
    taxes_dec, taxes_int = labeled.get('tax', ([], []))
    subtotals_dec, subtotals_int = labeled.get('subtotal', ([], []))
    nets_dec, nets_int = labeled.get('net', ([], []))
    
    expanded_totals_int = expand_decimal_candidates(totals_int)
    expanded_taxes_int = expand_decimal_candidates(taxes_int)
    expanded_subtotals_int = expand_decimal_candidates(subtotals_int)
    expanded_nets_int = expand_decimal_candidates(nets_int)
    
    totals = sorted(set(totals_dec + expanded_totals_int))
    taxes = sorted(set(taxes_dec + expanded_taxes_int))
    subtotals = sorted(set(subtotals_dec + expanded_subtotals_int))
    nets = sorted(set(nets_dec + expanded_nets_int))
    
    best_match = None
    best_error = float('inf')
    
    # Combine subtotal candidates
    subtotal_candidates = list(set(subtotals + nets))
    
    # Strategy 1: Direct match - subtotal + tax = total
    for t in totals:
        for v in taxes:
            for s in subtotal_candidates:
                error = abs(s + v - t)
                if error < 0.02 and error < best_error:
                    best_error = error
                    best_match = (t, v)
    
    # Strategy 2: If we have total and tax but no clear subtotal,
    # check if total - tax gives a reasonable subtotal
    if best_match is None:
        for t in totals:
            for v in taxes:
                implied_subtotal = t - v
                if implied_subtotal > 0:
                    # Check if implied subtotal exists in candidates
                    for n in all_candidates:
                        if abs(n - implied_subtotal) < 0.02:
                            error = abs(n + v - t)
                            if error < best_error:
                                best_error = error
                                best_match = (t, v)
    
    # Strategy 3: Tax rate computation - compute tax from rate * subtotal
    # This handles cases where tax is expressed only as a percentage
    if text and subtotal_candidates and totals:
        tax_rates = find_tax_rates(text)
        for rate in tax_rates:
            for s in subtotal_candidates:
                computed_tax = round(s * rate / 100, 2)
                computed_total = s + computed_tax
                # Check if computed total matches any labeled total
                for t in totals:
                    if abs(computed_total - t) < 0.02:
                        error = abs(computed_total - t)
                        if error < best_error:
                            best_error = error
                            best_match = (t, computed_tax)
    
    # Strategy 4: If total is clear but tax needs to be computed from rate
    # Look for patterns like "VAT 10%" or "GST 20%"
    if best_match is None and totals:
        for t in totals:
            for s in subtotal_candidates:
                implied_tax = t - s
                if implied_tax > 0:
                    # Check if this tax value exists in candidates
                    for n in all_candidates:
                        if abs(n - implied_tax) < 0.02:
                            if abs(s + n - t) < 0.02:
                                best_match = (t, n)
                                break
    
    # Strategy 5: Just use the largest total and a tax value
    if best_match is None and totals and taxes:
        best_match = (max(totals), max(taxes))
    
    return best_match


def classify_document(text: str) -> str:
    """
    Classify a document as 'invoice' or 'other' based on structural financial patterns.
    
    Invoice indicators (structural):
    - Has a customer/client/bill-to party
    - Describes goods or services with amounts
    - Shows tax/VAT as a separate line
    - States a total amount due/payable
    - Requests payment (explicitly or implicitly)
    
    Non-invoice indicators:
    - Explicitly disclaims invoice status
    - Is a request-to-buy not a request-for-payment (Purchase Order)
    - Is an internal accounting document (Expense Reimbursement)
    - Is a post-hoc reminder referencing a prior invoice (Payment Reminder)
    """
    text_lower = text.lower()
    
    # Strong non-invoice signals
    non_invoice_signals = []
    
    # Explicit disclaimer
    if re.search(r'not\s+(?:a\s+)?(?:tax\s+)?invoice', text_lower):
        non_invoice_signals.append('explicit_disclaimer')
    
    # Purchase order (request to buy, not request for payment)
    if re.search(r'purchase\s*order', text_lower):
        non_invoice_signals.append('purchase_order')
    if re.search(r'approval\s*status\s*:\s*pending', text_lower):
        non_invoice_signals.append('pending_approval')
    
    # Expense reimbursement (internal document)
    if re.search(r'expense\s*reimbursement', text_lower):
        non_invoice_signals.append('expense_reimbursement')
    if re.search(r'reimbursement\s*summary', text_lower):
        non_invoice_signals.append('reimbursement_summary')
    
    # Payment reminder (references prior invoice)
    if re.search(r'payment\s*reminder', text_lower):
        non_invoice_signals.append('payment_reminder')
    if re.search(r'(?:this\s+)?notice\s+is\s+not', text_lower):
        non_invoice_signals.append('notice_disclaimer')
    
    # Receipt / proof of payment (completed transaction, not a payment request)
    if re.search(r'receipt', text_lower):
        non_invoice_signals.append('receipt')
    if re.search(r'(?:card\s+)?payment\s+approved', text_lower):
        non_invoice_signals.append('payment_approved')
    
    # If strong non-invoice signals, classify as other
    if len(non_invoice_signals) >= 1:
        return 'other'
    
    # Invoice signals (structural)
    invoice_signals = []
    
    # Has customer/client/bill-to
    if re.search(r'(?:client|customer|bill\s*to|ship\s*to)\s*:', text_lower):
        invoice_signals.append('customer_field')
    
    # Has goods/services description with amounts
    if re.search(r'(?:services?|goods?|freight|retainer|consulting|hardware|meals|order)\s*[\d:]', text_lower):
        invoice_signals.append('goods_services')
    
    # Has tax/VAT as separate line
    if re.search(r'(?:vat|tax|gst|sales\s*tax)\s*[\d:]', text_lower):
        invoice_signals.append('tax_line')
    
    # Has total amount due/payable
    if re.search(r'(?:total|amount\s*due|payable|grand\s*total)\s*[\d:]', text_lower):
        invoice_signals.append('total_field')
    
    # Document type indicators that suggest invoice
    invoice_type_patterns = [
        r'(?:tax\s+)?document',
        r'billing\s*statement',
        r'remittance\s*notice',
        r'charge\s*note',
        r'(?:tax\s+)?invoice',
    ]
    for pat in invoice_type_patterns:
        if re.search(pat, text_lower):
            invoice_signals.append('invoice_type_label')
            break
    
    # Request for payment
    if re.search(r'(?:please\s+remit|payment\s+due|amount\s*due|total\s*due|payable)', text_lower):
        invoice_signals.append('payment_request')
    
    # Arithmetic validation: if subtotal + tax = total, it's almost certainly an invoice
    labeled = find_labeled_amounts(text)
    decimal_nums, integer_nums = extract_all_numbers(text)
    arith_result = arithmetic_cross_validate(labeled, decimal_nums, integer_nums, text)
    if arith_result:
        invoice_signals.append('arithmetic_valid')
    
    # Classification decision
    # Need at least 2 invoice signals to classify as invoice
    if len(invoice_signals) >= 2:
        return 'invoice'
    
    # Default to other if ambiguous
    return 'other'


def extract_financial_data(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract total_amount and vat_amount from document text using
    arithmetic cross-validation.
    
    Returns (total_amount, vat_amount) or (None, None) if extraction fails.
    """
    labeled = find_labeled_amounts(text)
    decimal_numbers, integer_numbers = extract_all_numbers(text)
    
    result = arithmetic_cross_validate(labeled, decimal_numbers, integer_numbers, text)
    if result:
        return result
    
    # Fallback: try to find total and tax from labeled amounts
    totals_dec, totals_int = labeled.get('total', ([], []))
    taxes_dec, taxes_int = labeled.get('tax', ([], []))
    
    totals = totals_dec + totals_int
    taxes = taxes_dec + taxes_int
    
    if totals and taxes:
        # Use the largest total (likely the grand total)
        total = max(totals)
        # Find a tax that makes arithmetic sense
        for tax in sorted(taxes, reverse=True):
            if tax < total:
                return (total, tax)
        return (total, taxes[0])
    
    return (None, None)


def process_documents(source_dir: str, invoices_dir: str, other_dir: str, 
                       summary_path: str) -> None:
    """
    Main processing function:
    1. Extract text from all documents
    2. Classify each as invoice or other
    3. Extract financial data from invoices
    4. Move files to appropriate directories
    5. Write summary.csv
    """
    # Create output directories
    os.makedirs(invoices_dir, exist_ok=True)
    os.makedirs(other_dir, exist_ok=True)
    
    # Find all PDF and image files
    supported_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.bmp', '.gif', '.webp'}
    files = []
    for fname in os.listdir(source_dir):
        ext = Path(fname).suffix.lower()
        if ext in supported_extensions:
            files.append(fname)
    
    files.sort()  # Process in consistent order
    
    invoice_rows = []
    
    for fname in files:
        filepath = os.path.join(source_dir, fname)
        
        # Extract text
        text = extract_text(filepath)
        
        # Classify
        doc_type = classify_document(text)
        
        if doc_type == 'invoice':
            # Extract financial data
            total_amount, vat_amount = extract_financial_data(text)
            
            if total_amount is not None and vat_amount is not None:
                invoice_rows.append({
                    'filename': fname,
                    'total_amount': f"{total_amount:.2f}",
                    'vat_amount': f"{vat_amount:.2f}",
                })
            
            # Move to invoices directory
            dest = os.path.join(invoices_dir, fname)
            shutil.move(filepath, dest)
        else:
            # Move to other directory
            dest = os.path.join(other_dir, fname)
            shutil.move(filepath, dest)
    
    # Write summary.csv
    with open(summary_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['filename', 'total_amount', 'vat_amount'])
        writer.writeheader()
        
        total_sum = 0.0
        vat_sum = 0.0
        
        for row in invoice_rows:
            writer.writerow(row)
            total_sum += float(row['total_amount'])
            vat_sum += float(row['vat_amount'])
        
        # Write totals row
        writer.writerow({
            'filename': 'total',
            'total_amount': f"{total_sum:.2f}",
            'vat_amount': f"{vat_sum:.2f}",
        })
    
    print(f"Processed {len(files)} documents:")
    print(f"  Invoices: {len(invoice_rows)}")
    print(f"  Other: {len(files) - len(invoice_rows)}")
    print(f"  Summary written to: {summary_path}")


def main():
    """Entry point for the document processor."""
    source_dir = os.environ.get('SOURCE_DIR', '/app/documents')
    invoices_dir = os.environ.get('INVOICES_DIR', '/app/invoices')
    other_dir = os.environ.get('OTHER_DIR', '/app/other')
    summary_path = os.environ.get('SUMMARY_PATH', '/app/invoices/summary.csv')
    
    if not os.path.isdir(source_dir):
        print(f"Error: Source directory '{source_dir}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    process_documents(source_dir, invoices_dir, other_dir, summary_path)


if __name__ == '__main__':
    main()
