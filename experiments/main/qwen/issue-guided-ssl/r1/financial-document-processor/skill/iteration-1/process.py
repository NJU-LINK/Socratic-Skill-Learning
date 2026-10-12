#!/usr/bin/env python3
"""
Financial Document Processor — Reusable Agent Skill

Classifies mixed financial documents (invoices vs. non-invoices), extracts
total_amount and vat_amount from invoices, routes files to output directories,
and produces summary.csv with a totals row.

Handles PDFs and images with OCR noise, multi-signal classification with
disclaimer vetoes, and diverse financial field labels.
"""

import os
import re
import csv
import sys
import glob
import shutil
import subprocess
import tempfile


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOCS_DIR = os.environ.get('DOCS_DIR', '/app/documents')
INVOICES_DIR = os.environ.get('INVOICES_DIR', '/app/invoices')
OTHER_DIR = os.environ.get('OTHER_DIR', '/app/other')

SUPPORTED_EXTS = ('.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff')


# ---------------------------------------------------------------------------
# Stage 1: Text Extraction
# ---------------------------------------------------------------------------

def extract_pdf(path: str) -> str:
    """Extract text from a PDF using pdftotext."""
    try:
        result = subprocess.run(
            ['pdftotext', path, '-'],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout
    except Exception:
        return ''


def extract_image(path: str):
    """Extract text from an image using tesseract with multiple PSM modes.
    Returns (best_text, merged_fields) where merged_fields is a dict with
    subtotal/vat/total if cross-PSM merging succeeds, else None."""
    all_texts = []

    # Try multiple PSM modes
    for psm in [4, 6, 11, 3]:
        try:
            result = subprocess.run(
                ['tesseract', path, 'stdout', '--psm', str(psm)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=30
            )
            text = result.stdout.strip()
            if text:
                all_texts.append(text)
        except Exception:
            continue

    # If sparse output, try preprocessing
    if not all_texts or max(len(t) for t in all_texts) < 30:
        try:
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
                tmp_path = tmp.name
            subprocess.run(
                ['convert', path, '-resize', '200%', '-sharpen', '0x1',
                 '-threshold', '45%', tmp_path],
                capture_output=True, timeout=30
            )
            for psm in [4, 6, 11]:
                try:
                    result = subprocess.run(
                        ['tesseract', tmp_path, 'stdout', '--psm', str(psm)],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, timeout=30
                    )
                    text = result.stdout.strip()
                    if text:
                        all_texts.append(text)
                except Exception:
                    continue
            os.unlink(tmp_path) if os.path.exists(tmp_path) else None
        except Exception:
            pass

    if not all_texts:
        return ('', None)

    # --- Cross-PSM field merging ---
    merged = _try_cross_psm_merge(all_texts)
    
    # Pick best text for classification (needs coherent prose)
    best_text = _pick_best_text(all_texts)
    
    return (best_text, merged)


def _pick_best_text(all_texts: list) -> str:
    """Pick the text with the most consistent financial structure for classification."""
    best_text = all_texts[0]
    best_score = -1

    for text in all_texts:
        score = 0
        lower = text.lower()
        # Check for financial structure
        has_sub = bool(re.search(r'subtot|subtoat|subtotat|subtotol', lower))
        has_tot = bool(re.search(r'total|totat|totol|pet\b|paid', lower))
        has_tax = bool(re.search(r'vat|tax|gst|nce|ncluded', lower))
        
        if has_sub: score += 2
        if has_tot: score += 2
        if has_tax: score += 2
        
        # Count numeric amounts with decimals
        amounts = re.findall(r'\d+\.\d{2}', text)
        score += len(amounts)
        # Prefer longer text as tiebreaker
        score += len(text) / 1000.0

        if score > best_score:
            best_score = score
            best_text = text

    return best_text


# Regex patterns for field candidate extraction
_SUB_LABELS = re.compile(r'subtot|subtoat|subtotat|subtotol|subtot', re.I)
_VAT_LABELS_PSM = re.compile(r'vat|tax(?!es)|gst|nce|ncluded', re.I)
# Total labels: match "total", "paid", "due" but NOT when preceded by "sub"
_TOT_LABELS = re.compile(r'(?<!sub)(total|totat|totol)|(?<!sub)tot\b|paid|due', re.I)
_AMOUNT_DEC = re.compile(r'(\d+\.\d{1,2})')
_AMOUNT_INT = re.compile(r'\b(\d{3,5})\b')


def _extract_field_candidates(text: str, label_re: re.Pattern) -> list:
    """Find amounts that appear near a matching label in the text."""
    candidates = []
    for m in label_re.finditer(text):
        after = text[m.end():m.end()+50]
        # Try decimal amounts first
        found = False
        for nm in _AMOUNT_DEC.finditer(after):
            v = float(nm.group(1))
            if v > 0:
                candidates.append(v)
                found = True
                break
        # If no decimal amount, try integer amounts (possible decimal loss)
        if not found:
            for nm in _AMOUNT_INT.finditer(after):
                raw = nm.group(1)
                v = float(raw[:-2] + '.' + raw[-2:]) if len(raw) >= 3 else float(raw)
                if v > 0:
                    candidates.append(v)
                    break
    return list(set(candidates))


def _try_cross_psm_merge(all_texts: list):
    """Try to find a consistent (subtotal, vat, total) across all PSM texts."""
    all_sub, all_vat, all_tot = [], [], []
    for text in all_texts:
        all_sub.extend(_extract_field_candidates(text, _SUB_LABELS))
        all_vat.extend(_extract_field_candidates(text, _VAT_LABELS_PSM))
        all_tot.extend(_extract_field_candidates(text, _TOT_LABELS))

    if not (all_sub and all_tot):
        return None

    # Count frequency of each candidate (values appearing in more PSM modes are more reliable)
    from collections import Counter
    sub_counts = Counter(all_sub)
    vat_counts = Counter(all_vat)
    tot_counts = Counter(all_tot)

    # Deduplicate
    all_sub = list(set(all_sub))
    all_vat = list(set(all_vat))
    all_tot = list(set(all_tot))

    # Find the combination where subtotal + vat ≈ total
    best = None
    best_error = float('inf')

    for s in all_sub:
        for t in all_tot:
            # Sanity: total must be strictly greater than subtotal
            if t <= s:
                continue
            # Sanity: total should be close to subtotal (within 30% for typical tax rates)
            if t < s * 0.7 or t > s * 1.5:
                continue
            
            # VAT can be explicit candidate or inferred
            vat_candidates = all_vat + [round(t - s, 2)]
            for v in vat_candidates:
                # Sanity: VAT should be positive and less than 50% of subtotal
                if v <= 0 or v > s * 0.5:
                    continue
                error = abs(s + v - t)
                # Prefer inferred VAT over explicit when error is small
                is_explicit_vat = v in all_vat
                # Give bonus to explicit VAT only if error is very small
                bonus = 0.02 if (is_explicit_vat and error < 0.01) else 0
                # Prefer values that appear in more PSM modes (more reliable)
                freq_bonus = (sub_counts.get(s, 0) + tot_counts.get(t, 0)) * 0.01
                if is_explicit_vat:
                    freq_bonus += vat_counts.get(v, 0) * 0.01
                # Prefer totals that are not also subtotal candidates
                not_subtotal_bonus = 0.03 if t not in all_sub else 0
                # Penalize high tax rates (VAT/subtotal > 20% is unusual)
                tax_rate = v / s if s > 0 else 0
                high_tax_penalty = 0.05 if tax_rate > 0.20 else 0
                # Score: lower is better
                score = error - bonus - freq_bonus - not_subtotal_bonus + high_tax_penalty
                if score < best_error:
                    best_error = score
                    best = {'subtotal': s, 'vat': round(v, 2), 'total': round(t, 2)}

    if best and best_error < 1.0:
        return best
    return None


def extract_text(path: str):
    """Extract text from a document based on its file extension.
    For images, returns (text, merged_fields) tuple.
    For PDFs, returns just text string."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf':
        return extract_pdf(path)
    elif ext in ('.jpg', '.jpeg', '.png', '.tif', '.tiff'):
        return extract_image(path)
    return ''


# ---------------------------------------------------------------------------
# OCR Cleanup Helpers
# ---------------------------------------------------------------------------

# Character substitution table for OCR noise in AMOUNT regions only
OCR_AMOUNT_SUBS = {
    'O': '0', 'o': '0',
    'I': '1', 'l': '1', '|': '1',
    'S': '5', 's': '5',
    'B': '8',
    'Z': '2', 'z': '2',
}


def clean_ocr_amount_text(text: str) -> str:
    """Apply OCR character substitution to amount-value text only."""
    result = []
    for ch in text:
        result.append(OCR_AMOUNT_SUBS.get(ch, ch))
    return ''.join(result)


def normalize_label(text: str) -> str:
    """Normalize a label for fuzzy matching: lowercase, strip non-alpha."""
    return re.sub(r'[^a-z]', '', text.lower())


def parse_number(s: str) -> float:
    """Parse a numeric string, handling commas, currency symbols, OCR noise."""
    # Strip currency symbols and whitespace
    s = re.sub(r'[€$£¥]', '', s)
    s = re.sub(r'\b(USD|EUR|GBP|JPY)\b', '', s)
    s = s.strip()

    # Remove thousands separators (commas)
    s = s.replace(',', '')

    # Apply OCR cleanup for digits
    s = clean_ocr_amount_text(s)

    # Try direct parse
    try:
        return round(float(s), 2)
    except ValueError:
        pass

    # Extract just digits and decimal point
    digits = re.sub(r'[^\d.]', '', s)
    try:
        return round(float(digits), 2)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Stage 2: Classification
# ---------------------------------------------------------------------------

def classify_document(text: str) -> str:
    """
    Classify a document as 'invoice' or 'other' using multi-signal scoring.
    Disclaimers are checked first and act as absolute vetoes.
    """
    lower = text.lower()
    normalized = normalize_label(text)

    # --- CRITICAL: Check disclaimers FIRST (immediate veto) ---
    disclaimer_patterns = [
        r'not\s+(a\s+)?(tax\s+)?invoice',
        r'not\s+a\s+bill',
        r'this\s+(is\s+)?(not|does\s+not\s+constitute)',
        r'notice\s+is\s+not',
    ]
    for pat in disclaimer_patterns:
        if re.search(pat, lower):
            return 'other'

    # --- Check document-type negatives (immediate veto) ---
    negative_doc_types = [
        'purchase order',
        'expense reimbursement',
        'payment reminder',
        'credit memo',
        'statement of account',
    ]
    for neg_type in negative_doc_types:
        if neg_type in lower:
            return 'other'

    # --- Accumulate positive and negative signals ---
    score = 0

    # Strong positive: explicit invoice markers
    if re.search(r'\b(invoice|tax invoice)\b', lower):
        score += 2

    # Strong positive: revenue document labels (invoice variants)
    if re.search(r'\b(charge note|billing statement|charge card)\b', lower):
        score += 2

    # Positive: remittance notice (invoice variant when it has transaction structure)
    if re.search(r'\bremittance\b', lower):
        # Check if it has transaction structure (amounts, tax, total)
        if re.search(r'(subtotal|total|tax|vat)', lower):
            score += 2
        else:
            score += 1

    # Positive: receipt with financial structure
    if re.search(r'\b(receipt|card payment)\b', lower):
        if re.search(r'(subtotal|total|vat|tax)', lower):
            score += 2
    # Fuzzy match for receipt/card payment (OCR noise)
    elif re.search(r'recei[cp]t|card\s+pay[a-z]*', normalized):
        if re.search(r'subtot|total|vat|tax', normalized):
            score += 2

    # Positive: "Tax Document" as title
    if re.search(r'\btax\s+document\b', lower):
        score += 2

    # Positive: transaction structure - Bill To / Ship To / Sold To
    if re.search(r'\b(bill to|ship to|sold to)\b', lower):
        score += 1

    # Positive: Customer/Client with named party
    if re.search(r'\b(customer|client)\s*:', lower):
        score += 1

    # Positive: total-with-tax labels
    if re.search(r'\b(grand total|amount due|total due|payable total|total paid)\b', lower):
        score += 1

    # Positive: tax line with amount
    if re.search(r'\b(vat|tax|gst|sales tax)\s*[:@]', lower):
        score += 1

    # Positive: line-item structure (service/product + amount)
    if re.search(r'(services|freight|design|consulting|hardware|order)\s*:?\s*[\d,]+\.?\d*', lower):
        score += 1

    # Positive: has subtotal + total structure
    if re.search(r'subtotal', lower) and re.search(r'total', lower):
        score += 1

    # Strong structural signal: subtotal-like + total-like + tax/vat-like
    # (robust to OCR noise — uses normalized text)
    has_subtotal_like = bool(re.search(r'subtot|subtotat|subtotol', normalized))
    has_total_like = bool(re.search(r'total|totat|totol|pet\b|paid', normalized))
    has_tax_like = bool(re.search(r'vat|tax|gst|nce|ncluded', normalized))
    if has_subtotal_like and has_total_like and has_tax_like:
        score += 2  # strong structural invoice signal

    # --- Negative signals ---
    # Internal/process language
    if re.search(r'\b(employee|approval status|approved by|reimbursement|reclaimable)\b', lower):
        score -= 2

    # PO/estimate language
    if re.search(r'\b(estimated tax|estimated total|requested total)\b', lower):
        score -= 1

    if re.search(r'\b(approved spend|pending|ceiling)\b', lower):
        score -= 1

    # "Prior Tax" or "Outstanding Balance" signals non-invoice
    if re.search(r'\b(prior tax|outstanding balance)\b', lower):
        score -= 1

    return 'invoice' if score >= 2 else 'other'


# ---------------------------------------------------------------------------
# Stage 3: Field Extraction
# ---------------------------------------------------------------------------

# Labels for total_amount (final amount including tax)
TOTAL_LABELS = [
    'grand total', 'total due', 'amount due', 'payable total',
    'invoice total', 'balance due', 'total amount', 'total paid',
    'net total', 'amount payable', 'total price', 'total with tax',
    'gross total', 'total',
]

# Exclusion contexts for total_amount
TOTAL_EXCLUSIONS = [
    'subtotal', 'sub-total', 'sub total',
    'requested', 'estimated', 'approved spend',
    'outstanding', 'prior', 'ceiling',
]

# Labels for vat_amount
VAT_LABELS = [
    'vat included', 'vat amount', 'vat',
    'tax amount', 'tax included', 'sales tax',
    'gst', 'tax',
]

# Exclusion contexts for vat_amount
VAT_EXCLUSIONS = [
    'estimated', 'prior', 'reclaimable', 'reclamation',
    'not a tax',
]


def find_amount(text: str, labels: list, exclude_labels: list = None) -> float:
    """
    Find the best amount matching any label, with exclusion context checking.
    Returns the largest valid amount found (tie-break by magnitude).
    """
    lower = text.lower()
    candidates = []

    for label in labels:
        # Find all occurrences of this label
        label_norm = normalize_label(label)
        # Search using fuzzy matching on the text
        for m in re.finditer(re.escape(label), lower):
            # Check exclusion context in a window around the match
            ctx_start = max(0, m.start() - 40)
            ctx_end = min(len(lower), m.end() + 60)
            context = lower[ctx_start:ctx_end]

            if exclude_labels:
                excluded = False
                for excl in exclude_labels:
                    if excl in context:
                        excluded = True
                        break
                if excluded:
                    continue

            # Look for an amount in the text after the label
            after_text = text[m.end():m.end() + 80]
            # Apply OCR cleanup to the after-text for amount parsing
            after_clean = clean_ocr_amount_text(after_text)

            # Skip past any percentage patterns (e.g., "10%:" or "20%")
            after_clean = re.sub(r'^\s*[\d.]+%\s*:?\s*', '', after_clean)

            # Find numeric values
            # Pattern: optional currency symbol, then digits with optional commas and decimal
            nums = re.findall(r'[\d,]+\.?\d*', after_clean)
            for n in nums:
                val = parse_number(n)
                if val is not None and val > 0:
                    candidates.append(val)
                    break  # one amount per label occurrence

    # Also try matching on normalized text for OCR-garbled labels
    text_normalized = normalize_label(text)
    for label in labels:
        label_norm = normalize_label(label)
        if len(label_norm) < 3:
            continue  # too short for fuzzy match
        for m in re.finditer(re.escape(label_norm), text_normalized):
            # Get the corresponding position in original text
            # (approximate — normalized text has different indices)
            # Instead, search original text near the label
            ctx_start = max(0, m.start() - 40)
            ctx_end = min(len(text_normalized), m.end() + 60)
            context = text_normalized[ctx_start:ctx_end]

            if exclude_labels:
                excluded = False
                for excl in exclude_labels:
                    excl_norm = normalize_label(excl)
                    if excl_norm in context:
                        excluded = True
                        break
                if excluded:
                    continue

            # Find amount in original text near this position
            # Map back to original text approximately
            orig_region = text[max(0, m.start() - 10):m.end() + 80]
            orig_clean = clean_ocr_amount_text(orig_region)
            # Skip past any percentage patterns
            orig_clean = re.sub(r'^\s*[\d.]+%\s*:?\s*', '', orig_clean)
            nums = re.findall(r'[\d,]+\.?\d*', orig_clean)
            for n in nums:
                val = parse_number(n)
                if val is not None and val > 0:
                    candidates.append(val)
                    break

    return max(candidates) if candidates else 0.0


def extract_all_amounts(text: str) -> list:
    """Extract all numeric amounts from text for consistency checking."""
    clean = clean_ocr_amount_text(text)
    amounts = []
    for m in re.finditer(r'[\d,]+\.\d{2}', clean):  # amounts with decimal
        val = parse_number(m.group())
        if val and val > 0:
            amounts.append(val)
    # Also get amounts without decimal (might be OCR errors)
    for m in re.finditer(r'\b(\d{3,})\b', clean):
        raw = m.group(1)
        # Try with decimal inserted before last 2 digits
        with_decimal = raw[:-2] + '.' + raw[-2:]
        val = parse_number(with_decimal)
        if val and val > 0:
            amounts.append(val)
    return amounts


def fix_ocr_decimal_issues(text: str, total: float, vat: float) -> tuple:
    """
    If total/vat seem wrong due to OCR decimal loss, try to fix.
    Heuristic: if an amount is ~100x larger than expected, decimal was lost.
    """
    # Get subtotal for consistency check
    subtotal = find_amount(text, ['subtotal', 'sub-total', 'sub total', 'subtoat', 'subtotol', 'subtotat'], None)
    
    if subtotal <= 0:
        return total, vat
    
    # Try all combinations of dividing total and vat by 100
    best_total, best_vat = total, vat
    best_error = float('inf')
    
    for t_div in [1, 100]:
        for v_div in [1, 100]:
            t_try = total / t_div if total > 0 else 0
            v_try = vat / v_div if vat > 0 else 0
            
            # Check consistency: subtotal + vat should equal total
            if t_try > 0 and v_try > 0:
                expected_total = subtotal + v_try
                error = abs(t_try - expected_total)
            elif t_try > 0:
                # No vat, just check if total is reasonable
                error = abs(t_try - subtotal * 1.1)  # expect ~10% tax
            else:
                continue
            
            if error < best_error:
                best_error = error
                best_total = round(t_try, 2)
                best_vat = round(v_try, 2)
    
    return best_total, best_vat


def extract_invoice_fields(text: str) -> dict:
    """Extract total_amount and vat_amount from an invoice document."""
    total = find_amount(text, TOTAL_LABELS, TOTAL_EXCLUSIONS)
    vat = find_amount(text, VAT_LABELS, VAT_EXCLUSIONS)

    # Fix OCR decimal issues
    total, vat = fix_ocr_decimal_issues(text, total, vat)

    # If total not found but we have subtotal and vat, compute total
    if total == 0.0:
        subtotal = find_amount(text, ['subtotal', 'sub-total', 'sub total', 'subtoat', 'subtotol', 'subtotat'], None)
        if subtotal > 0 and vat > 0:
            total = round(subtotal + vat, 2)

    # If vat not found but we have total and subtotal, compute vat
    if vat == 0.0 and total > 0.0:
        subtotal = find_amount(text, ['subtotal', 'sub-total', 'sub total', 'subtoat', 'subtotol', 'subtotat'], None)
        if subtotal > 0 and total > subtotal:
            vat = round(total - subtotal, 2)

    # If vat still not found, try to infer from line items and total
    # Look for the pattern: service/amount + unexplained_amount + total
    if vat == 0.0 and total > 0.0:
        # Find all amounts in the text
        clean_text = clean_ocr_amount_text(text)
        all_amounts = []
        for m in re.finditer(r'[\d,]+\.\d{2}', clean_text):
            val = parse_number(m.group())
            if val and val > 0 and val < total:
                all_amounts.append(val)
        # If we have exactly 2 amounts and they sum to total, the smaller is vat
        if len(all_amounts) >= 2:
            unique_amounts = sorted(set(all_amounts), reverse=True)
            for i, amt in enumerate(unique_amounts):
                remainder = round(total - amt, 2)
                if remainder in unique_amounts and remainder > 0:
                    vat = remainder
                    break

    return {'total_amount': total, 'vat_amount': vat}


# ---------------------------------------------------------------------------
# Stage 4: Main Pipeline
# ---------------------------------------------------------------------------

def main():
    """Main processing pipeline."""
    # Create output directories
    os.makedirs(INVOICES_DIR, exist_ok=True)
    os.makedirs(OTHER_DIR, exist_ok=True)

    # Collect all supported documents
    docs = []
    for entry in sorted(os.listdir(DOCS_DIR)):
        path = os.path.join(DOCS_DIR, entry)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(entry)[1].lower()
        if ext in SUPPORTED_EXTS:
            docs.append(path)

    if not docs:
        print("No supported documents found in", DOCS_DIR)
        # Still create empty summary
        write_summary([])
        return

    invoice_rows = []

    for path in docs:
        fname = os.path.basename(path)
        print(f"Processing: {fname}")

        # Stage 1: Extract text
        extracted = extract_text(path)
        
        # Handle tuple return from images (text, merged_fields)
        if isinstance(extracted, tuple):
            text, merged = extracted
        else:
            text = extracted
            merged = None
        
        print(f"  Extracted {len(text)} chars")
        if merged:
            print(f"  Cross-PSM merged: subtotal={merged['subtotal']}, vat={merged['vat']}, total={merged['total']}")

        # Stage 2: Classify
        classification = classify_document(text)
        print(f"  Classification: {classification}")

        if classification == 'invoice':
            # Stage 3: Extract fields
            if merged:
                # Use cross-PSM merged values directly
                fields = {'total_amount': merged['total'], 'vat_amount': merged['vat']}
            else:
                fields = extract_invoice_fields(text)
            print(f"  total_amount={fields['total_amount']}, vat_amount={fields['vat_amount']}")
            invoice_rows.append({
                'filename': fname,
                'total_amount': fields['total_amount'],
                'vat_amount': fields['vat_amount'],
            })
            # Stage 4: Route to invoices
            shutil.move(path, os.path.join(INVOICES_DIR, fname))
        else:
            # Stage 4: Route to other
            shutil.move(path, os.path.join(OTHER_DIR, fname))

    # Write summary.csv
    write_summary(invoice_rows)
    print(f"\nDone. {len(invoice_rows)} invoices processed.")
    print(f"Documents dir empty: {len(os.listdir(DOCS_DIR)) == 0}")


def write_summary(invoice_rows: list):
    """Write summary.csv with invoice rows and a totals row."""
    summary_path = os.path.join(INVOICES_DIR, 'summary.csv')
    with open(summary_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])

        sum_total = 0.0
        sum_vat = 0.0

        for row in invoice_rows:
            # Format amounts with 2 decimal places
            total_str = f"{row['total_amount']:.2f}"
            vat_str = f"{row['vat_amount']:.2f}"
            writer.writerow([row['filename'], total_str, vat_str])
            sum_total += row['total_amount']
            sum_vat += row['vat_amount']

        # Final totals row
        writer.writerow(['total', f"{round(sum_total, 2):.2f}", f"{round(sum_vat, 2):.2f}"])


if __name__ == '__main__':
    main()
