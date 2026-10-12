#!/usr/bin/env python3
"""
Financial Document Processor
Classifies documents as invoice/other, extracts financial fields,
moves files to appropriate directories, and writes summary.csv.

Handles OCR noise via multi-pass extraction and arithmetic cross-validation.

Key semantic distinction:
- Invoice = request for payment (billing statement, tax document, charge note)
- Receipt = proof of payment already made (card payment approved, total paid)
- Other non-invoices: purchase orders, expense reports, payment reminders
"""

import os
import re
import csv
import subprocess
import shutil
from pathlib import Path
from collections import Counter

# Directories - adjust if mounted differently
DOCS_DIR = Path(os.environ.get("DOCS_DIR", "/app/documents"))
INVOICES_DIR = Path(os.environ.get("INVOICES_DIR", "/app/invoices"))
OTHER_DIR = Path(os.environ.get("OTHER_DIR", "/app/other"))
SUMMARY_PATH = INVOICES_DIR / "summary.csv"

# Supported file extensions
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"}
ALL_EXTS = PDF_EXTS | IMAGE_EXTS


def extract_text_from_pdf(filepath):
    """Extract text from a PDF using pdftotext."""
    try:
        result = subprocess.run(
            ["pdftotext", filepath, "-"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout
    except Exception:
        return ""


def extract_text_from_image(filepath):
    """Extract text from an image using tesseract with multiple PSM modes."""
    texts = []
    for psm in [3, 4, 6, 11]:
        try:
            result = subprocess.run(
                ["tesseract", filepath, "-", "--psm", str(psm)],
                capture_output=True, text=True, timeout=30
            )
            if result.stdout.strip():
                texts.append(result.stdout)
        except Exception:
            pass
    return "\n".join(texts)


def extract_text(filepath):
    """Extract text from a document based on its extension."""
    ext = Path(filepath).suffix.lower()
    if ext in PDF_EXTS:
        return extract_text_from_pdf(filepath)
    elif ext in IMAGE_EXTS:
        return extract_text_from_image(filepath)
    return ""


def classify_document(text):
    """
    Classify a document as 'invoice' or 'other'.
    
    Key semantic distinction:
    - Invoice = request for payment (billing statement, tax document, charge note)
    - Receipt = proof of payment already made (card payment approved, total paid)
    - Other non-invoices: purchase orders, expense reports, payment reminders
    
    Priority-ordered signal system:
    1. Non-invoice overrides (strongest signal)
    2. Invoice type patterns
    3. Structural signals (combination required)
    4. Default to 'other'
    """
    text_lower = text.lower()

    # --- Step 1: Non-invoice overrides ---
    
    # Explicit disclaimers
    if re.search(r'not\s+a\s+tax\s+invoice', text_lower):
        return "other"
    if re.search(r'not\s+an\s+invoice', text_lower):
        return "other"
    if re.search(r'this\s+notice\s+is\s+not', text_lower):
        return "other"
    
    # Document types that are not invoices
    if re.search(r'purchase\s+order', text_lower):
        return "other"
    if re.search(r'expense\s+reimbursement', text_lower):
        return "other"
    if re.search(r'expense\s+report', text_lower):
        return "other"
    if re.search(r'payment\s+reminder', text_lower):
        return "other"
    if re.search(r'remittance\s+advice', text_lower):
        return "other"
    if re.search(r'approval\s+status:\s*pending', text_lower):
        return "other"
    if re.search(r'pending\s+approval', text_lower):
        return "other"
    
    # Receipts = proof of payment, NOT requests for payment
    # Key signals: "payment approved", "total paid", "card payment"
    if re.search(r'payment\s+approv', text_lower):
        return "other"
    if re.search(r'total\s+paid', text_lower):
        return "other"
    if re.search(r'card\s+payment', text_lower):
        return "other"
    # Receipt variants (OCR-noisy)
    if re.search(r'\brecei[pc]*t\b', text_lower):
        return "other"
    if re.search(r'\brecep[tc]?\b', text_lower):
        return "other"

    # --- Step 2: Invoice type patterns ---
    if re.search(r'\binvoice\b', text_lower):
        return "invoice"
    if re.search(r'\bbilling\s+statement\b', text_lower):
        return "invoice"
    if re.search(r'\btax\s+document\b', text_lower):
        return "invoice"
    if re.search(r'\bcharge\s+note\b', text_lower):
        return "invoice"
    if re.search(r'\btax\s+invoice\b', text_lower):
        return "invoice"

    # --- Step 3: Structural signals ---
    has_customer = bool(re.search(
        r'(bill\s+to|customer|client|ship\s+to)\s*:', text_lower
    ))
    has_amount_due = bool(re.search(
        r'(amount\s+due|total\s+due|payable\s+total|grand\s+total)',
        text_lower
    ))
    has_tax = bool(re.search(r'(vat|tax|gst|sales\s+tax)', text_lower))
    has_remit = bool(re.search(
        r'(please\s+remit|payment\s+due|due\s+within|net\s+\d+)', text_lower
    ))

    if has_customer and has_amount_due:
        return "invoice"
    if has_remit and has_tax:
        return "invoice"
    if re.search(r'remittance\s+notice', text_lower) and has_amount_due and has_tax:
        return "invoice"

    # --- Step 4: Default ---
    return "other"


def parse_amount(text):
    """Parse a monetary amount from text, handling commas and currency symbols."""
    text = text.strip()
    text = re.sub(r'[€$£¥,\s]', '', text)
    try:
        return float(text)
    except ValueError:
        return 0.0


def fix_missing_decimal(num_str):
    """
    Fix numbers that might have missing decimals due to OCR.
    For monetary amounts, prefer 2 decimal places.
    E.g., "483" -> 4.83, "5420" -> 54.20
    """
    num_str = re.sub(r'[€$£¥,\s]', '', num_str)

    if '.' in num_str:
        try:
            return [float(num_str)]
        except ValueError:
            return []

    # For monetary amounts, prefer 2 decimal places
    if len(num_str) >= 3:
        candidate = num_str[:-2] + '.' + num_str[-2:]
        try:
            val = float(candidate)
            if val > 0:
                return [val]
        except ValueError:
            pass

    return []


def find_most_stable_value(values, tolerance=0.5):
    """
    Find the most stable value from a list of OCR readings.
    Groups values within tolerance and returns the largest group's median.
    """
    if not values:
        return None

    sorted_vals = sorted(values)
    groups = []

    for val in sorted_vals:
        placed = False
        for group in groups:
            if abs(val - group[0]) < tolerance:
                group.append(val)
                placed = True
                break
        if not placed:
            groups.append([val])

    if groups:
        largest_group = max(groups, key=len)
        return sorted(largest_group)[len(largest_group) // 2]

    return None


def extract_financial_fields(text):
    """
    Extract total_amount and vat_amount from document text.
    Uses a three-strategy cascade:
    1. Arithmetic-first (subtotal + VAT = total)
    2. Explicit value extraction with OCR-tolerant patterns
    3. Arithmetic inference for missing fields
    """
    result = {"total_amount": 0.0, "vat_amount": 0.0}

    # --- Find subtotals (OCR-tolerant) ---
    subtotal_patterns = [
        r'subto\w*\s*:?\s*[€$£]?\s*([\d,]+\.?\d*)',
        r'(?:net\s+charges?)\s*:?\s*[€$£]?\s*([\d,]+\.?\d*)',
    ]

    subtotals_found = []
    for pattern in subtotal_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            amount = parse_amount(match.group(1))
            if amount > 0:
                subtotals_found.append(amount)

    # Line-item amounts that could be subtotals
    line_item_patterns = [
        r'(?:services?|order|retainer|item|product)\s*:?\s*[€$£]?\s*([\d,]+\.\d{2})',
    ]
    for pattern in line_item_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            amount = parse_amount(match.group(1))
            if amount > 0:
                subtotals_found.append(amount)

    # --- Find VAT/tax (OCR-tolerant) ---
    vat_patterns = [
        r'vat\w*\s*(?:\d+%\s*)?\w*\s*:?\s*[€$£]?\s*([\d,]+\.?\d*)',
        r'(?:sales\s+tax)\s*:?\s*[€$£]?\s*([\d,]+\.?\d*)',
        r'(?:gst|tax)\w*\s*:?\s*[€$£]?\s*([\d,]+\.?\d*)',
        r'(?:st|ast)\s*(\d+\.\d{2})',  # OCR noise: "st78.40"
    ]

    vat_found = []
    for pattern in vat_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            amt_str = match.group(1)
            candidates = fix_missing_decimal(amt_str)
            vat_found.extend(candidates)

    # --- Find totals (OCR-tolerant) ---
    total_patterns = [
        r'(?:grand\s+total|amount\s+due|total\s+due|payable\s+total)\s*:?\s*[€$£]?\s*([\d,]+\.?\d*)',
        r'(?:total\w*|otal\w*)\s*(?:paid|pet|due)?\s*:?\s*[€$£]?\s*([\d,]+\.?\d*)',
    ]

    totals_found = []
    for pattern in total_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            amt_str = match.group(1)
            candidates = fix_missing_decimal(amt_str)
            totals_found.extend(candidates)

    # --- Strategy 1: Arithmetic-first ---
    stable_subtotal = find_most_stable_value(subtotals_found)
    stable_vat = find_most_stable_value(vat_found)

    if stable_subtotal and stable_vat:
        computed_total = stable_subtotal + stable_vat
        result["total_amount"] = round(computed_total, 2)
        result["vat_amount"] = round(stable_vat, 2)

        # Verify against explicit total if available
        if totals_found:
            stable_total = find_most_stable_value(totals_found)
            if stable_total and abs(stable_total - computed_total) < 1.0:
                result["total_amount"] = round(stable_total, 2)

        return result

    # --- Strategy 2: Use explicit values ---
    if totals_found:
        stable_total = find_most_stable_value(totals_found)
        if stable_total:
            result["total_amount"] = round(stable_total, 2)

    if vat_found:
        if stable_subtotal and result["total_amount"] > 0:
            implied_vat = result["total_amount"] - stable_subtotal
            if implied_vat > 0:
                result["vat_amount"] = round(implied_vat, 2)
            else:
                stable_vat_val = find_most_stable_value(vat_found)
                if stable_vat_val:
                    result["vat_amount"] = round(stable_vat_val, 2)
        else:
            stable_vat_val = find_most_stable_value(vat_found)
            if stable_vat_val:
                result["vat_amount"] = round(stable_vat_val, 2)

    # --- Strategy 3: Arithmetic inference ---
    if result["vat_amount"] == 0.0 and result["total_amount"] > 0 and stable_subtotal:
        implied_vat = result["total_amount"] - stable_subtotal
        if implied_vat > 0:
            result["vat_amount"] = round(implied_vat, 2)

    return result


def process_documents():
    """Main processing pipeline."""
    # Create output directories
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)

    # Collect document files
    doc_files = []
    for f in sorted(DOCS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in ALL_EXTS:
            doc_files.append(f)

    invoices = []

    for doc_path in doc_files:
        # Extract text
        text = extract_text(str(doc_path))

        # Classify
        classification = classify_document(text)

        if classification == "invoice":
            # Extract financial fields
            fields = extract_financial_fields(text)

            invoices.append({
                "filename": doc_path.name,
                "total_amount": fields["total_amount"],
                "vat_amount": fields["vat_amount"],
            })

            # Move to invoices directory
            dest = INVOICES_DIR / doc_path.name
            shutil.move(str(doc_path), str(dest))
        else:
            # Move to other directory
            dest = OTHER_DIR / doc_path.name
            shutil.move(str(doc_path), str(dest))

    # Write summary.csv
    with open(SUMMARY_PATH, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["filename", "total_amount", "vat_amount"])

        total_sum = 0.0
        vat_sum = 0.0

        for inv in invoices:
            writer.writerow([
                inv["filename"],
                f"{inv['total_amount']:.2f}",
                f"{inv['vat_amount']:.2f}",
            ])
            total_sum += inv["total_amount"]
            vat_sum += inv["vat_amount"]

        # Total row
        writer.writerow([
            "total",
            f"{total_sum:.2f}",
            f"{vat_sum:.2f}",
        ])

    # Verify documents directory is empty
    remaining = list(DOCS_DIR.iterdir())
    if remaining:
        print(f"WARNING: {len(remaining)} files remaining in {DOCS_DIR}")
        for f in remaining:
            print(f"  - {f.name}")

    return len(invoices), total_sum, vat_sum


if __name__ == "__main__":
    n_invoices, total_sum, vat_sum = process_documents()
    print(f"Processed {n_invoices} invoices")
    print(f"Total amount: {total_sum:.2f}")
    print(f"Total VAT: {vat_sum:.2f}")
