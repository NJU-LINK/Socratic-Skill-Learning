#!/usr/bin/env python3
"""
Financial Document Processor
Classifies mixed document batches into invoices and non-invoices,
extracts financial fields from invoices, and produces a summary CSV.

Handles variation dimensions:
- document_content_patterns: various document types with overlapping vocabulary
- document_modality_and_ocr_noise: PDFs, JPGs, noisy OCR with dropped decimals
- financial_field_expression: varied labels and numeric formats
- batch_scale_and_class_balance: arbitrary batch sizes and class distributions
"""

import os
import re
import csv
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Tuple, Set

# ─── Configuration ───────────────────────────────────────────────────────────

DOCUMENTS_DIR = "/app/documents"
INVOICES_DIR = "/app/invoices"
OTHER_DIR = "/app/other"
SUMMARY_CSV = os.path.join(INVOICES_DIR, "summary.csv")

# ─── Text Extraction ────────────────────────────────────────────────────────

def extract_text_from_pdf(filepath: str) -> str:
    """Extract text from PDF. Tries pdftotext, then PyMuPDF, then OCR fallback."""
    # Try pdftotext with layout first
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", filepath, "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Try pdftotext without layout
    try:
        result = subprocess.run(
            ["pdftotext", filepath, "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback to PyMuPDF
    try:
        import fitz
        doc = fitz.open(filepath)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        combined = "\n".join(text_parts).strip()
        if combined:
            return combined
    except Exception:
        pass

    # Last resort: OCR on rendered pages
    try:
        import fitz
        from PIL import Image
        import pytesseract
        import io

        doc = fitz.open(filepath)
        text_parts = []
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text_parts.append(pytesseract.image_to_string(img))
        doc.close()
        return "\n".join(text_parts).strip()
    except Exception:
        return ""


def extract_text_from_image(filepath: str) -> str:
    """
    Extract text from image using tesseract with multiple strategies.
    Combines results from multiple PSM modes and image enhancements
    to maximize information capture from noisy scans.
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        import pytesseract

        img = Image.open(filepath)
        all_texts = []

        # Try multiple PSM modes on original image
        for psm in [6, 4, 3, 11, 12]:
            try:
                text = pytesseract.image_to_string(img, config=f'--psm {psm}')
                if text.strip():
                    all_texts.append(text)
            except Exception:
                continue

        # Try with contrast-enhanced image
        try:
            enhanced = img.copy()
            enhancer = ImageEnhance.Contrast(enhanced)
            enhanced = enhancer.enhance(2.0)
            enhanced = enhanced.filter(ImageFilter.SHARPEN)
            for psm in [6, 4, 3]:
                try:
                    text = pytesseract.image_to_string(enhanced, config=f'--psm {psm}')
                    if text.strip():
                        all_texts.append(text)
                except Exception:
                    continue
        except Exception:
            pass

        # Combine all texts for maximum information
        return "\n".join(all_texts).strip()
    except Exception:
        # Fallback to command-line tesseract
        try:
            result = subprocess.run(
                ["tesseract", filepath, "stdout", "--psm", "6"],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout.strip()
        except Exception:
            return ""


def extract_text(filepath: str) -> str:
    """Extract text from any supported document format."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"):
        return extract_text_from_image(filepath)
    else:
        try:
            with open(filepath, 'r', errors='ignore') as f:
                return f.read().strip()
        except Exception:
            return ""


# ─── Number Parsing ──────────────────────────────────────────────────────────

# Patterns for monetary amounts with decimal points (high confidence)
# Matches: 1,280.00 | 1058.40 | 54.20 | 751.68 | 0.00
# Also matches European format: 1.280,00 | 1.100,00
# Order matters: European format (with dot-thousands) must come first
AMOUNT_DECIMAL = r'(\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{1,2}|\d+,\d{1,2})'

def parse_amount(text: str) -> Optional[float]:
    """Parse a monetary amount from text string.
    
    Handles:
    - Standard format: 1,280.00 or 1058.40
    - European format: 1.280,00 (dot for thousands, comma for decimal)
    - Plain European: 100,00 or 78,40 (comma decimal, no dot-thousands)
    - Plain integers: 5420 (may need decimal recovery)
    """
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r'[\u20ac$£¥\s]', '', cleaned)
    cleaned = re.sub(r'[,;:]+$', '', cleaned)

    # European format with dot-thousands: 1.280,00 or 1.000,00
    match = re.search(r'^(\d{1,3}(?:\.\d{3})+,\d{2})$', cleaned)
    if match:
        return float(match.group(1).replace('.', '').replace(',', '.'))

    match = re.search(r'(\d{1,3}(?:\.\d{3})+,\d{2})', cleaned)
    if match:
        return float(match.group(1).replace('.', '').replace(',', '.'))

    # Plain European: 100,00 or 78,40 (comma decimal, no dot-thousands)
    # Must come before standard patterns to prevent \d+ from matching just "100"
    # Negative lookahead ensures we don't match standard format like "1,280.00"
    match = re.search(r'^(\d+,\d{1,2})(?![\d.])$', cleaned)
    if match:
        return float(match.group(1).replace(',', '.'))

    match = re.search(r'(\d+,\d{1,2})(?![\d.])', cleaned)
    if match:
        return float(match.group(1).replace(',', '.'))

    # Standard format: 1,280.00 or 1058.40
    match = re.search(r'^(\d{1,3}(?:,\d{3})*\.\d{1,2})$', cleaned)
    if match:
        return float(match.group(1).replace(',', ''))

    match = re.search(r'^(\d+\.\d{1,2})$', cleaned)
    if match:
        return float(match.group(1))

    match = re.search(r'(\d+\.\d{1,2})', cleaned)
    if match:
        return float(match.group(1))

    match = re.search(r'(\d+)', cleaned)
    if match:
        return float(int(match.group(1)))

    return None


def decimal_insertion_variants(n: float) -> List[float]:
    """
    Generate all plausible decimal insertion variants of an integer.
    E.g., 5420 -> [5.420, 54.20, 542.0]
    Used for OCR noise recovery when decimal points are dropped.
    """
    s = str(int(n))
    variants = []
    for pos in range(1, len(s)):
        v = float(s[:pos] + '.' + s[pos:])
        if v > 0.001:  # skip trivially small values
            variants.append(v)
    return variants


def extract_tax_rate(text: str) -> Optional[float]:
    """
    Extract tax rate percentage from text.
    Handles patterns like: "VAT 10%", "Tax 20%", "GST 15%", "10% VAT"
    Returns the rate as a decimal (e.g., 10% -> 0.10) or None if not found.
    """
    # Pattern: label followed by percentage
    patterns = [
        r'(?:vat|gst|tax|sales\s+tax)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%',
        r'(\d+(?:\.\d+)?)\s*%\s*(?:vat|gst|tax)',
        r'(?:vat|gst|tax)\s+(\d+(?:\.\d+)?)\s*%',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                rate = float(match.group(1))
                if 0 < rate <= 100:  # reasonable tax rate range
                    return rate / 100.0
            except (ValueError, AttributeError):
                pass
    return None


# ─── Document Classification ─────────────────────────────────────────────────

def classify_document(text: str) -> str:
    """
    Classify a document as 'invoice' or 'other' based on content analysis.

    Uses a weighted scoring system:
    - Strong non-invoice signals override everything (explicit disclaimers)
    - Document title/heading carries strong weight
    - Body content patterns contribute incrementally

    Returns 'invoice' or 'other'.
    """
    text_lower = text.lower()

    # ── Strong non-invoice signals (immediate rejection) ──
    strong_non_invoice = [
        r'not\s+(?:a\s+)?(?:tax\s+)?invoice',
        r'this\s+(?:document|notice)\s+is\s+not',
        r'purchase\s+order\b',
        r'\bpo\s*(?:number|#|no)[\s:.]',
        r'expense\s+(?:reimbursement|report|claim)\b',
        r'payment\s+reminder\b',
        r'reimbursement\s+summary\b',
        r'approval\s+status\s*:\s*pending',
        r'approved\s+spend\s+ceiling',
        # Receipt signals: proof of payment already made, not a billing request
        # Handle OCR noise: "payment" → "fayment", "approved" → "aeproved"
        r'card\s+[pf]ayment\s+a[ep]rov',
        r'payment\s+[aep]rov',
    ]
    for pattern in strong_non_invoice:
        if re.search(pattern, text_lower):
            return "other"

    # ── Score-based classification ──
    score = 0

    # Title/heading analysis (first 5 lines)
    first_lines = "\n".join(text.split("\n")[:5]).lower()

    title_invoice_indicators = {
        'invoice': 5, 'proforma': 4, 'charge not': 4,
        'tax document': 3, 'billing statement': 3,
    }
    title_non_invoice_indicators = {
        'purchase order': -5, 'payment reminder': -5,
        'expense reimbursement': -5, 'reimbursement summary': -5,
        'reminder': -3, 'receipt': -5,
    }

    for phrase, weight in title_non_invoice_indicators.items():
        if phrase in first_lines:
            score += weight

    for phrase, weight in title_invoice_indicators.items():
        if phrase in first_lines:
            score += weight

    # Body content: strong invoice patterns
    body_invoice_patterns = [
        (r'\binvoice\b', 3),
        (r'\bproforma\b', 3),
        (r'\bcredit\s+note\b', 3),
        (r'\bcharge\s+not[e(s)]*\b', 3),
        (r'\bamount\s+due\b', 3),
        (r'\btotal\s+due\b', 3),
        (r'\bpayable\s+total\b', 3),
        (r'\bgrand\s+total\b', 3),
        (r'please\s+remit', 3),
        (r'\bbill\s+to\b', 2),
    ]
    for pattern, weight in body_invoice_patterns:
        if re.search(pattern, text_lower):
            score += weight

    # Body content: moderate invoice patterns
    moderate_invoice_patterns = [
        (r'\bvat\b', 1), (r'\bgst\b', 1), (r'\bsales\s+tax\b', 1),
        (r'\bsubtotal\b', 1), (r'\bnet\s+charges\b', 1),
        (r'\bclient\s*:', 1), (r'\bcustomer\s*:', 1),
        (r'\bship\s+to\b', 1),
    ]
    for pattern, weight in moderate_invoice_patterns:
        if re.search(pattern, text_lower):
            score += weight

    # Compound signals (title + body combination)
    if 'tax document' in first_lines and ('remit' in text_lower or 'grand total' in text_lower):
        score += 3
    if 'billing statement' in first_lines and 'amount due' in text_lower:
        score += 3
    if 'remittance' in first_lines and ('payable total' in text_lower or 'sales tax' in text_lower):
        score += 3

    # Body content: non-invoice patterns
    body_non_invoice_patterns = [
        (r'\breminder\b', -2),
        (r'\boutstanding\s+balance\b', -2),
        (r'\bprior\s+tax\b', -2),
        (r'\brequested\s+total\b', -2),
        (r'\bestimated\s+tax\b', -2),
        (r'\breimbursement\b', -3),
        (r'\bemployee\s*:', -2),
        (r'\bapproved\s+(?:meals|total|tax)\b', -2),
        (r'\breclaimable\b', -2),
        # Receipt signals: proof of payment already made
        # Handle OCR noise: "Total Paid" → "otal Paid", "Total Pet", "Total Pid"
        (r'(?:total|otal)\s+(?:paid|pet|pid)\b', -3),
        (r'\breceipt\b', -3),
        # OCR-noisy receipt variants
        (r'\brecei[pc]t\b', -3),
    ]
    for pattern, weight in body_non_invoice_patterns:
        if re.search(pattern, text_lower):
            score += weight  # weight is negative

    return "invoice" if score > 0 else "other"


# ─── Financial Field Extraction ──────────────────────────────────────────────

# Label patterns for identifying which field an amount belongs to
TOTAL_LABEL_PATTERNS = [
    r'(?<!sub)(?:grand\s+)?total(?:\s+(?:due|paid|pet|pid|amount))?',
    r'(?<!sub)(?:otal\s+(?:due|paid|pet|pid))',
    r'amount\s+due',
    r'payable\s+total',
    r'(?<!sub)(?:otal\s+)?[Dd]us',
    r'eal\s+due',
]

VAT_LABEL_PATTERNS = [
    r'vat(?:\s+(?:included|inc\w*|nctuded|inetuded))?',
    r'gst',
    r'sales\s+tax',
    r'(?<!\w)tax(?:\s+\d+%)?',
    r'(?:ast|est|st)(?:\s*\d)',  # OCR-noisy tax labels
]

SUBTOTAL_LABEL_PATTERNS = [
    r'sub\s*total',
    r'subtoat',
    r'subtott',
    r'subtest',
    r'net\s+charges',
]


def _extract_integer_amounts_from_labeled_lines(
    text: str, label_patterns: List[str]
) -> List[float]:
    """
    Extract integer-only amounts from lines that match financial label patterns.
    These are candidates where OCR dropped the decimal point.

    Only accepts integers from lines where:
    1. A financial label is present
    2. An integer (no decimal point) is the primary numeric token
    3. The integer is in a plausible monetary range (2-99999)
    """
    candidates = []
    combined_label_re = re.compile(
        '|'.join(f'(?:{p})' for p in label_patterns), re.IGNORECASE
    )

    for line in text.split('\n'):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Check if line has a matching financial label
        if not combined_label_re.search(line_stripped):
            continue

        # Skip lines that look like dates or reference numbers
        if re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', line_stripped):
            continue
        if re.search(r'(?:ref|po|doc|id|number|#)\s*[:\-]?\s*\w*[\-]?\d+', line_stripped, re.IGNORECASE):
            # But don't skip if there's also a financial label with an amount
            pass

        # Find integer amounts on this line (no decimal point)
        # Match integers that are NOT part of a decimal number
        for match in re.finditer(r'(?<![.\d])(\d{2,6})(?![.\d])', line_stripped):
            val = int(match.group(1))
            # Filter: plausible monetary range, not a year (1900-2099), not tiny
            if 2 <= val <= 99999 and not (1900 <= val <= 2099 and len(match.group(1)) == 4):
                # Additional check: make sure this integer isn't part of a date
                context_start = max(0, match.start() - 10)
                context = line_stripped[context_start:match.end()]
                if not re.search(r'\d{4}[-/]\d{2}', context):
                    candidates.append(float(val))

    return candidates


def _extract_decimal_amount(text: str, label_patterns: List[str],
                            amount_pattern: str = AMOUNT_DECIMAL) -> List[Tuple[float, int]]:
    """
    Extract decimal amounts near financial labels.
    Returns list of (value, priority_score) tuples.
    """
    results = []
    for label_pat in label_patterns:
        # Pattern: label followed by optional separator then amount
        full_pattern = (
            r'(?:' + label_pat + r')\s*(?:\d+%)?\s*[:\-]?\s*[\$€£]?\s*'
            + amount_pattern
        )
        for match in re.finditer(full_pattern, text, re.IGNORECASE):
            val = parse_amount(match.group(1))
            if val is not None and val > 0:
                results.append((val, 0))
    return results


def extract_financial_fields(text: str) -> dict:
    """
    Extract total_amount and vat_amount from invoice text.

    Two-tier extraction strategy:
    - Tier 1 (high confidence): decimal amounts matched by labeled patterns
    - Tier 2 (OCR noise recovery): integer amounts from labeled lines,
      corrected via arithmetic validation (total ≈ subtotal + vat)

    Handles the critical OCR failure mode where decimal points are dropped:
    "5420" → 54.20, "489" → 4.89

    Returns dict with 'total_amount' and 'vat_amount' (floats or None).
    """
    result = {"total_amount": None, "vat_amount": None}

    # ── Step 1: Extract subtotal (usually reliable - has decimal) ──
    subtotal_candidates = []
    for label_pat in SUBTOTAL_LABEL_PATTERNS:
        full_pattern = (
            r'(?:' + label_pat + r')\s*[:\-]?\s*[\$€£]?\s*' + AMOUNT_DECIMAL
        )
        for match in re.finditer(full_pattern, text, re.IGNORECASE):
            val = parse_amount(match.group(1))
            if val and val > 0:
                subtotal_candidates.append(val)

    # Pick the most common subtotal, or the first one
    subtotal = None
    if subtotal_candidates:
        # Use frequency to pick the most likely correct value
        from collections import Counter
        counts = Counter(subtotal_candidates)
        subtotal = counts.most_common(1)[0][0]

    # ── Step 2: Tier 1 - Extract decimal amounts with labels ──
    # Total: look for labeled decimal amounts
    total_t1_candidates = []
    total_label_patterns_t1 = [
        r'(?:grand\s+total|total\s+due|amount\s+due|payable\s+total|total\s+paid)',
        r'(?:otal\s+due|otal\s+paid|otal\s+pet|otal\s+pid|eal\s+due|and\s+total)',
        r'(?<!sub)(?:^|\n)\s*total',
        r'(?<!sub)total\w*',
        r'(?<!sub)(?:otal\s+)?[Dd]us',
    ]
    for label_pat in total_label_patterns_t1:
        full_pattern = (
            r'(?:' + label_pat + r')\s*[:\-]?\s*[\$€£]?\s*' + AMOUNT_DECIMAL
        )
        for match in re.finditer(full_pattern, text, re.IGNORECASE):
            val = parse_amount(match.group(1))
            if val and val > 0:
                total_t1_candidates.append(val)

    # VAT: look for labeled decimal amounts
    vat_t1_candidates = []
    vat_label_patterns_t1 = [
        r'vat\s*(?:included|inc\w*|nctuded|inetuded)',
        r'(?:vat|gst|sales\s+tax)\s*(?:\d+%)?',
        r'(?<!no\s)(?<!prior\s)(?<!not\s)(?<!estimated\s)(?<!reclaimable\s)\btax\s*(?:\d+%)?',
        r'(?:^|\n)\s*(?:ast|est|st)',
        r'(?:vat|tax)\s+\d+%',
    ]
    for label_pat in vat_label_patterns_t1:
        full_pattern = (
            r'(?:' + label_pat + r')\s*[:\-]?\s*[\$€£]?\s*' + AMOUNT_DECIMAL
        )
        for match in re.finditer(full_pattern, text, re.IGNORECASE):
            val = parse_amount(match.group(1))
            if val and val > 0:
                vat_t1_candidates.append(val)

    # Also extract VAT with permissive pattern (captures integers like "489")
    vat_permissive_candidates = []
    vat_permissive_patterns = [
        r'vat\s*(?:included|inc\w*|nctuded|inetuded)\s*[:\-]?\s*[\$€£]?\s*(\d+\.?\d*)',
    ]
    for pat in vat_permissive_patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            val = parse_amount(match.group(1))
            if val and val > 0:
                vat_permissive_candidates.append(val)

    # ── Step 3: If both total and vat found via tier 1 (decimal), validate ──
    total_t1 = max(total_t1_candidates) if total_t1_candidates else None
    vat_t1 = max(vat_t1_candidates) if vat_t1_candidates else None

    if total_t1 and vat_t1:
        result["total_amount"] = total_t1
        result["vat_amount"] = vat_t1
        # Validate with arithmetic if subtotal available
        if subtotal:
            expected = round(subtotal + vat_t1, 2)
            if abs(total_t1 - expected) > 2.0:
                # Tier 1 values might be wrong; try tier 2 recovery
                pass  # fall through to tier 2
            else:
                return result

    # ── Step 4: Tier 2 - Extract integer candidates from labeled lines ──
    total_int_candidates = _extract_integer_amounts_from_labeled_lines(
        text, TOTAL_LABEL_PATTERNS
    )
    vat_int_candidates = _extract_integer_amounts_from_labeled_lines(
        text, VAT_LABEL_PATTERNS
    )

    # Also include permissive VAT extractions (integers like 489.0)
    for v in vat_permissive_candidates:
        if v == int(v) and v > 10 and v not in vat_int_candidates:
            vat_int_candidates.append(v)

    # ── Step 5: Simultaneous arithmetic recovery ──
    # Try all combinations of (subtotal, total_variant, vat_variant)
    # and select the one with best arithmetic consistency

    # Build option lists
    total_options = list(set(total_t1_candidates)) if total_t1_candidates else []
    vat_options = list(set(vat_t1_candidates)) if vat_t1_candidates else []
    subtotal_options = list(set(subtotal_candidates)) if subtotal_candidates else [None]

    # Add decimal insertion variants for integer candidates
    for raw in set(total_int_candidates):
        for variant in decimal_insertion_variants(raw):
            if variant not in total_options:
                total_options.append(variant)

    for raw in set(vat_int_candidates):
        for variant in decimal_insertion_variants(raw):
            if variant not in vat_options:
                vat_options.append(variant)

    # Try all combinations of (subtotal, total_variant, vat_variant)
    if total_options and vat_options:
        best_combo = None
        best_score = float('inf')

        # Use actual subtotals if available, otherwise try with None
        sub_list = [s for s in subtotal_options if s is not None]
        if not sub_list:
            sub_list = [None]  # no subtotal available, use frequency heuristic

        # Count frequency of each candidate (correct values appear more often)
        from collections import Counter
        total_freq = Counter(total_t1_candidates) if total_t1_candidates else Counter()
        vat_freq = Counter(vat_t1_candidates) if vat_t1_candidates else Counter()

        for sub in sub_list:
            for t in total_options:
                for v in vat_options:
                    if sub is not None:
                        # Primary: arithmetic validation
                        error = abs(t - (sub + v))
                        if error > 2.0:
                            continue  # reject inconsistent combinations
                        score = error
                    else:
                        # No subtotal: use frequency + ratio heuristic
                        # Correct values appear in multiple OCR passes
                        t_count = total_freq.get(t, 0)
                        v_count = vat_freq.get(v, 0)
                        freq_score = -(t_count + v_count)  # negative because higher is better

                        # VAT should be 1-50% of total for typical invoices
                        if t <= 0 or v <= 0 or v >= t:
                            continue
                        ratio = v / t
                        if not (0.01 <= ratio <= 0.50):
                            continue
                        # Prefer ratios in typical tax range (5-25%)
                        ratio_score = abs(ratio - 0.15)

                        # Combine: frequency is primary, ratio is secondary
                        score = freq_score * 10 + ratio_score

                    if score < best_score:
                        best_score = score
                        best_combo = (t, v)

        if best_combo:
            result["total_amount"] = round(best_combo[0], 2)
            result["vat_amount"] = round(best_combo[1], 2)
            return result

    # ── Step 6: Partial recovery ──
    # If we have total but not vat, compute vat from total - subtotal
    if total_t1 and subtotal and not vat_t1:
        result["total_amount"] = total_t1
        computed_vat = round(total_t1 - subtotal, 2)
        if computed_vat > 0:
            result["vat_amount"] = computed_vat
        return result

    # If we have vat but not total, compute total from subtotal + vat
    if vat_t1 and subtotal and not total_t1:
        result["vat_amount"] = vat_t1
        result["total_amount"] = round(subtotal + vat_t1, 2)
        return result

    # If we have total from tier 2 but no vat
    if total_options and subtotal and not vat_options:
        best_total = min(total_options, key=lambda t: abs(t - (subtotal + 0)))
        # This doesn't help without vat info
        pass

    # ── Step 7: Rate-based tax computation ──
    # If we have subtotal but no explicit tax amount, try computing from tax rate
    if subtotal and not result["vat_amount"]:
        tax_rate = extract_tax_rate(text)
        if tax_rate:
            computed_vat = round(subtotal * tax_rate, 2)
            if computed_vat > 0:
                result["vat_amount"] = computed_vat
                # If we also don't have total, compute it
                if not result["total_amount"]:
                    result["total_amount"] = round(subtotal + computed_vat, 2)
                return result

    # ── Step 8: Last resort fallbacks ──
    # Use whatever tier 1 values we have
    if not result["total_amount"] and total_t1:
        result["total_amount"] = total_t1
    if not result["vat_amount"] and vat_t1:
        result["vat_amount"] = vat_t1

    # If still no total, use the largest decimal amount in the document
    if not result["total_amount"]:
        all_decimal_amounts = []
        for match in re.finditer(AMOUNT_DECIMAL, text):
            val = parse_amount(match.group(1))
            if val and val > 0:
                all_decimal_amounts.append(val)
        if all_decimal_amounts:
            result["total_amount"] = max(all_decimal_amounts)

    # If still no vat but we have total and subtotal, compute it
    if not result["vat_amount"] and result["total_amount"] and subtotal:
        computed_vat = round(result["total_amount"] - subtotal, 2)
        if computed_vat > 0:
            result["vat_amount"] = computed_vat

    return result


# ─── Main Processing Pipeline ────────────────────────────────────────────────

def get_document_files(directory: str) -> List[str]:
    """Get all PDF and image files from the documents directory."""
    supported_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    files = []
    for entry in os.listdir(directory):
        filepath = os.path.join(directory, entry)
        if os.path.isfile(filepath):
            ext = os.path.splitext(entry)[1].lower()
            if ext in supported_extensions:
                files.append(filepath)
    return sorted(files)


def process_documents():
    """Main processing pipeline."""
    # Create output directories
    os.makedirs(INVOICES_DIR, exist_ok=True)
    os.makedirs(OTHER_DIR, exist_ok=True)

    # Get all document files
    doc_files = get_document_files(DOCUMENTS_DIR)
    if not doc_files:
        print("No documents found in", DOCUMENTS_DIR)
        return

    print(f"Found {len(doc_files)} documents to process")

    invoices = []  # List of (filename, total_amount, vat_amount)

    for filepath in doc_files:
        filename = os.path.basename(filepath)
        print(f"\nProcessing: {filename}")

        # Extract text
        text = extract_text(filepath)
        if not text:
            print(f"  WARNING: Could not extract text from {filename}")
            dest = os.path.join(OTHER_DIR, filename)
            shutil.move(filepath, dest)
            continue

        print(f"  Extracted text ({len(text)} chars)")

        # Classify
        classification = classify_document(text)
        print(f"  Classification: {classification}")

        if classification == "invoice":
            # Extract financial fields
            fields = extract_financial_fields(text)
            total_amount = fields["total_amount"]
            vat_amount = fields["vat_amount"]

            print(f"  Total: {total_amount}, VAT: {vat_amount}")

            # Move to invoices directory
            dest = os.path.join(INVOICES_DIR, filename)
            shutil.move(filepath, dest)

            if total_amount is not None and total_amount > 0:
                invoices.append((filename, total_amount, vat_amount or 0.0))
            else:
                # CRITICAL: Do NOT silently write 0.00
                # This would corrupt the summary totals
                print(f"  WARNING: Could not reliably extract total_amount for {filename}")
                print(f"  Extracted values: total={total_amount}, vat={vat_amount}")
                # Still include the row but with best available data
                # Use 0.0 only as absolute last resort (extraction completely failed)
                invoices.append((filename, total_amount or 0.0, vat_amount or 0.0))
        else:
            # Move to other directory
            dest = os.path.join(OTHER_DIR, filename)
            shutil.move(filepath, dest)

    # Write summary CSV
    print(f"\nWriting summary CSV with {len(invoices)} invoices...")
    with open(SUMMARY_CSV, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])

        total_sum = 0.0
        vat_sum = 0.0

        for filename, total, vat in invoices:
            writer.writerow([filename, f"{total:.2f}", f"{vat:.2f}"])
            total_sum += total
            vat_sum += vat

        # Add total row
        writer.writerow(['total', f"{total_sum:.2f}", f"{vat_sum:.2f}"])

    print(f"Summary written to {SUMMARY_CSV}")
    print(f"Total invoices: {len(invoices)}")
    print(f"Grand total: {total_sum:.2f}")
    print(f"Total VAT: {vat_sum:.2f}")

    # Verify documents directory is empty
    remaining = [f for f in os.listdir(DOCUMENTS_DIR)
                 if os.path.isfile(os.path.join(DOCUMENTS_DIR, f))]
    if remaining:
        print(f"WARNING: {len(remaining)} files remaining in documents dir")
    else:
        print("Documents directory is empty - OK")


if __name__ == "__main__":
    process_documents()
