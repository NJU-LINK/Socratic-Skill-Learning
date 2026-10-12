#!/usr/bin/env python3
"""
Financial Document Processor
- Classifies documents as invoice or other using scoring-based approach
- Extracts total_amount and vat_amount from invoices using multi-OCR arithmetic validation
- Moves files to appropriate directories
- Creates summary.csv
"""

import os
import re
import csv
import shutil
import fitz  # PyMuPDF
from PIL import Image
import pytesseract
from collections import Counter

DOCUMENTS_DIR = '/app/documents'
INVOICES_DIR = '/app/invoices'
OTHER_DIR = '/app/other'

def extract_text_from_pdf(filepath):
    """Extract text from PDF using PyMuPDF"""
    text = ""
    try:
        doc = fitz.open(filepath)
        for page in doc:
            text += page.get_text()
    except Exception as e:
        print(f"Error extracting PDF {filepath}: {e}")
    return [text]

def extract_text_from_image(filepath):
    """Extract text from image using multiple OCR modes for robustness"""
    texts = []
    try:
        img = Image.open(filepath)
        for psm in [3, 6, 11]:
            text = pytesseract.image_to_string(img, config=f'--psm {psm}')
            texts.append(text)
    except Exception as e:
        print(f"Error extracting image {filepath}: {e}")
    return texts

def classify_document(texts):
    """
    Classify document as invoice or other using scoring-based approach.
    KEY DISTINCTION: Invoice = request for payment ("Total Due")
                     Receipt = proof of payment ("Total Paid", "Payment Approved")
    """
    all_lines = []
    for text in texts:
        all_lines.extend([line.lower() for line in text.split('\n')])
    
    score = 0
    
    # Positive signals for invoice (request for payment)
    positive_patterns = [
        'amount due',
        'grand total',
        'total due',
        'payable total',
        'vat',
        'sales tax',
        'tax',
        'bill to',
        'customer',
        'ship to',
        'invoice',
        'please remit',
        'billing statement',
        'charge',
        'subtotal',
        'subtot',
        'tax document',
    ]
    
    matched_positive = []
    for pattern in positive_patterns:
        for line in all_lines:
            if pattern in line:
                score += 1
                matched_positive.append(pattern)
                break
    
    # Negative signals - CRITICAL: distinguish paid vs due
    negative_signals = [
        ('not a tax invoice', 5),
        ('not an invoice', 5),
        ('purchase order', 4),
        ('pending', 2),
        ('estimated tax', 2),
        ('expense reimbursement', 4),
        ('reimbursement summary', 3),
        ('payment reminder', 3),
        ('outstanding balance', 2),
        # Receipt indicators (payment already made)
        ('payment approved', 5),
        ('card payment', 4),
        ('total paid', 4),
        ('paid', 2),  # Generic paid indicator
    ]
    
    combined_text = ' '.join(all_lines)
    matched_negative = []
    for pattern, weight in negative_signals:
        if pattern in combined_text:
            score -= weight
            matched_negative.append(pattern)
    
    print(f"  Classification score: {score}")
    return score >= 3

def extract_numbers_from_line(line):
    """Extract all numbers from a line"""
    nums = re.findall(r'[\d,]+\.?\d*', line)
    result = []
    for n in nums:
        try:
            clean = n.replace(',', '')
            if clean:
                result.append(float(clean))
        except:
            pass
    return result

def extract_tax_amount(line):
    """
    Extract tax amount from a line, handling patterns like:
    - "VAT 10%: 128.00" -> 128.00
    - "Tax: 55.68" -> 55.68
    - "VAT included 4.83" -> 4.83
    """
    line_lower = line.lower()
    
    # Check if line contains tax-related keywords
    if not any(p in line_lower for p in ['vat', 'tax', 'gst', 'sales tax', 'ast']):
        return None
    
    # Extract all numbers
    nums = extract_numbers_from_line(line)
    if not nums:
        return None
    
    # If there's a percentage pattern like "10%", skip that number
    percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%', line_lower)
    if percent_match:
        percent_val = float(percent_match.group(1))
        nums = [n for n in nums if abs(n - percent_val) > 0.01]
    
    # Return the largest remaining number
    if nums:
        return max(nums)
    return None

def extract_amounts_by_frequency_and_scale(texts):
    """
    Extract total_amount and vat_amount using:
    1. Frequency voting on RAW values across all OCR runs
    2. Scale search on the most frequent value
    3. Arithmetic validation
    """
    # Step 1: Collect RAW values from each OCR run
    raw_subtotals = []
    raw_taxes = []
    raw_totals = []
    
    for text in texts:
        for line in text.lower().split('\n'):
            nums = extract_numbers_from_line(line)
            if not nums:
                continue
            
            # Extract subtotal
            if any(p in line for p in ['subtotal', 'subtot', 'subtest', 'net charges']):
                if nums:
                    raw_subtotals.append(nums[0])
            
            # Extract tax
            elif any(p in line for p in ['vat', 'tax', 'gst', 'sales tax', 'ast']):
                tax_val = extract_tax_amount(line)
                if tax_val is not None:
                    raw_taxes.append(tax_val)
            
            # Extract total
            elif any(p in line for p in ['total due', 'total paid', 'grand total', 'amount due', 
                                          'payable total', 'total pet', 'teal due', 'total']):
                if 'subtotal' not in line and 'subtot' not in line:
                    if nums:
                        raw_totals.append(nums[0])
    
    print(f"  Raw values - Subtotals: {raw_subtotals}, Taxes: {raw_taxes}, Totals: {raw_totals}")
    
    # Step 2: Find most frequent RAW value for each field
    most_freq_subtotal = Counter(raw_subtotals).most_common(1)[0][0] if raw_subtotals else None
    most_freq_tax = Counter(raw_taxes).most_common(1)[0][0] if raw_taxes else None
    most_freq_total = Counter(raw_totals).most_common(1)[0][0] if raw_totals else None
    
    print(f"  Most frequent raw - Subtotal: {most_freq_subtotal}, Tax: {most_freq_tax}, Total: {most_freq_total}")
    
    # Step 3: Try scales on the most frequent values and validate with arithmetic
    scales = [1, 10, 100, 1000, 0.1, 0.01, 0.001]
    
    best_subtotal = None
    best_tax = None
    best_total = None
    best_validation_score = -1
    
    # If we have all three fields, find scale combination that validates
    if most_freq_subtotal and most_freq_tax and most_freq_total:
        for sub_scale in scales:
            for tax_scale in scales:
                for total_scale in scales:
                    scaled_sub = most_freq_subtotal * sub_scale
                    scaled_tax = most_freq_tax * tax_scale
                    scaled_total = most_freq_total * total_scale
                    
                    # Validate: subtotal + tax ≈ total
                    calculated_total = scaled_sub + scaled_tax
                    error = abs(calculated_total - scaled_total)
                    
                    if error < scaled_total * 0.02:  # 2% tolerance
                        validation_score = 1.0 / (error + 0.01)  # Prefer smaller error
                        
                        if validation_score > best_validation_score:
                            best_validation_score = validation_score
                            best_subtotal = scaled_sub
                            best_tax = scaled_tax
                            best_total = scaled_total
    
    # If we have subtotal and tax but no total, calculate total
    elif most_freq_subtotal and most_freq_tax:
        for sub_scale in scales:
            for tax_scale in scales:
                scaled_sub = most_freq_subtotal * sub_scale
                scaled_tax = most_freq_tax * tax_scale
                
                # Validate tax rate is reasonable (5-25%)
                calculated_total = scaled_sub + scaled_tax
                tax_rate = scaled_tax / calculated_total if calculated_total > 0 else 0
                
                if 0.05 <= tax_rate <= 0.25:
                    validation_score = 1.0 / (abs(tax_rate - 0.15) + 0.01)  # Prefer ~15% tax rate
                    
                    if validation_score > best_validation_score:
                        best_validation_score = validation_score
                        best_subtotal = scaled_sub
                        best_tax = scaled_tax
                        best_total = calculated_total
    
    # If we only have total and tax
    elif most_freq_total and most_freq_tax:
        for total_scale in scales:
            for tax_scale in scales:
                scaled_total = most_freq_total * total_scale
                scaled_tax = most_freq_tax * tax_scale
                
                # Validate tax rate is reasonable (5-25%)
                tax_rate = scaled_tax / scaled_total if scaled_total > 0 else 0
                
                if 0.05 <= tax_rate <= 0.25:
                    validation_score = 1.0 / (abs(tax_rate - 0.15) + 0.01)
                    
                    if validation_score > best_validation_score:
                        best_validation_score = validation_score
                        best_total = scaled_total
                        best_tax = scaled_tax
                        best_subtotal = scaled_total - scaled_tax
    
    # If we only have total
    elif most_freq_total:
        for total_scale in scales:
            scaled_total = most_freq_total * total_scale
            if scaled_total > 10:  # Reasonable invoice amount
                best_total = scaled_total
                best_tax = 0
                best_subtotal = scaled_total
                break
    
    print(f"  Best scaled - Subtotal: {best_subtotal}, Tax: {best_tax}, Total: {best_total}")
    
    # Return total and tax
    total_amount = best_total
    vat_amount = best_tax if best_tax is not None else 0
    
    print(f"  Extracted: Total={total_amount}, VAT={vat_amount}")
    return total_amount, vat_amount

def process_single_document(filename, texts):
    """Process a single document"""
    print(f"\nProcessing: {filename}")
    
    is_invoice = classify_document(texts)
    
    if is_invoice:
        total_amount, vat_amount = extract_amounts_by_frequency_and_scale(texts)
        print(f"  → INVOICE: Total={total_amount}, VAT={vat_amount}")
        return True, total_amount, vat_amount
    else:
        print(f"  → OTHER")
        return False, None, None

def main():
    os.makedirs(INVOICES_DIR, exist_ok=True)
    os.makedirs(OTHER_DIR, exist_ok=True)
    
    invoices = []
    
    for filename in sorted(os.listdir(DOCUMENTS_DIR)):
        filepath = os.path.join(DOCUMENTS_DIR, filename)
        
        if not os.path.isfile(filepath):
            continue
        
        if filename.lower().endswith('.pdf'):
            texts = extract_text_from_pdf(filepath)
        elif filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            texts = extract_text_from_image(filepath)
        else:
            continue
        
        is_invoice, total_amount, vat_amount = process_single_document(filename, texts)
        
        if is_invoice:
            dest = os.path.join(INVOICES_DIR, filename)
            shutil.move(filepath, dest)
            invoices.append({
                'filename': filename,
                'total_amount': total_amount,
                'vat_amount': vat_amount
            })
        else:
            dest = os.path.join(OTHER_DIR, filename)
            shutil.move(filepath, dest)
    
    # Create summary.csv
    summary_path = os.path.join(INVOICES_DIR, 'summary.csv')
    with open(summary_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['filename', 'total_amount', 'vat_amount'])
        writer.writeheader()
        
        total_sum = 0
        vat_sum = 0
        
        for inv in invoices:
            formatted_inv = {
                'filename': inv['filename'],
                'total_amount': f"{inv['total_amount']:.2f}" if inv['total_amount'] is not None else "0.00",
                'vat_amount': f"{inv['vat_amount']:.2f}" if inv['vat_amount'] is not None else "0.00"
            }
            writer.writerow(formatted_inv)
            total_sum += float(formatted_inv['total_amount'])
            vat_sum += float(formatted_inv['vat_amount'])
        
        writer.writerow({
            'filename': 'total',
            'total_amount': f"{total_sum:.2f}",
            'vat_amount': f"{vat_sum:.2f}"
        })
    
    print(f"\n{'='*60}")
    print(f"Summary written to {summary_path}")
    print(f"Total invoices: {len(invoices)}")
    print(f"Total amount: {total_sum}")
    print(f"Total VAT: {vat_sum}")

if __name__ == '__main__':
    main()
