#!/usr/bin/env python3
"""
Financial Document Processor
=============================
Classify mixed batches of financial documents (PDFs and images) as invoice or
other, extract total_amount and vat_amount from invoices, move files to
designated directories, and produce a summary CSV.

Architecture:
- Text extraction produces MULTIPLE candidate texts (OCR diversity)
- Classification and field extraction operate on ALL candidates
- Best value per field is selected by label priority, not text selection

Handles noisy OCR, varied document titles, multiple financial field expression
styles, and arbitrary batch sizes.

Usage:
    python3 process_documents.py

Requirements (pre-installed in task environment):
    - pytesseract, Pillow (image OCR)
    - PyMuPDF/fitz (fallback PDF extraction)
    - pdftotext CLI (primary PDF extraction)
"""

import os
import re
import csv
import shutil
import subprocess
from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# ── Configuration ──────────────────────────────────────────────────────────
DOCS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
SUMMARY_PATH = INVOICES_DIR / "summary.csv"

SUPPORTED_EXTS = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}


# ── Text Extraction (multi-candidate) ──────────────────────────────────────

def extract_texts_from_pdf(filepath):
    """Extract text candidates from PDF. Returns list of texts."""
    texts = []

    # Primary: pdftotext
    try:
        result = subprocess.run(
            ["pdftotext", str(filepath), "-"],
            capture_output=True, text=True, timeout=30
        )
        text = result.stdout.strip()
        if text and len(text) > 20:
            texts.append(text)
    except Exception:
        pass

    # Fallback: PyMuPDF
    try:
        import fitz
        doc = fitz.open(str(filepath))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        text = text.strip()
        if text and len(text) > 20:
            texts.append(text)
    except Exception:
        pass

    return texts if texts else [""]


def extract_texts_from_image(filepath):
    """Extract multiple OCR candidate texts from image.

    Runs multiple preprocessing × PSM combinations and returns ALL non-empty
    results. Downstream stages (classification, extraction) operate on the
    full set and select the best per-field, rather than collapsing to one text.
    """
    texts = []
    try:
        from PIL import Image, ImageEnhance
        import pytesseract

        img = Image.open(str(filepath))

        # Prepare image variants
        variants = [("original", img)]

        img_gray = img.convert('L')
        variants.append(("gray", img_gray))

        img_enhanced = ImageEnhance.Contrast(img_gray).enhance(2.0)
        variants.append(("enhanced", img_enhanced))

        try:
            img_sharp = ImageEnhance.Sharpness(img_gray).enhance(2.0)
            variants.append(("sharp", img_sharp))
        except Exception:
            pass

        # Run all PSM modes on each variant
        for name, variant_img in variants:
            for psm in [3, 4, 6, 11, 12]:
                try:
                    text = pytesseract.image_to_string(variant_img, config=f'--psm {psm}')
                    if text and text.strip():
                        texts.append(text.strip())
                except Exception:
                    pass

    except Exception:
        pass

    # Deduplicate (keep order, remove exact duplicates)
    seen = set()
    unique = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return unique if unique else [""]


def extract_texts(filepath):
    """Extract multiple text candidates from any supported file type."""
    ext = filepath.suffix.lower()
    if ext == '.pdf':
        return extract_texts_from_pdf(filepath)
    elif ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'):
        return extract_texts_from_image(filepath)
    return [""]


# ── Amount Parsing (format-aware) ──────────────────────────────────────────

# Format-specific amount capture groups
US_AMOUNT = r'([\d,]+(?:\.\d+)?)'   # US: 1,234.56 (comma=grouping, period=decimal)
EU_AMOUNT = r'([\d.]+(?:,\d+)?)'    # EU: 1.234,56 (period=grouping, comma=decimal)


def detect_number_format(texts):
    """Detect whether document uses US or European number format.
    
    US:  1,234.56  (comma=grouping, period=decimal)
    EU:  1.234,56  (period=grouping, comma=decimal)
    
    Counts signals across all texts and returns the dominant format.
    """
    if isinstance(texts, str):
        texts = [texts]
    
    eu_signals = 0
    us_signals = 0
    
    for text in texts:
        # EU: comma followed by exactly 2 digits (decimal comma)
        # e.g., "234,56", "1.000,00", "18,50"
        # Must NOT be followed by more digits (to avoid matching "1,234" as EU)
        eu_signals += len(re.findall(r'\d+,\d{2}(?:\b|[^0-9])', text))
        
        # US: period followed by exactly 2 digits (decimal period)
        # e.g., "234.56", "1,000.00", "18.50"
        us_signals += len(re.findall(r'\d+\.\d{2}(?:\b|[^0-9])', text))
    
    return "european" if eu_signals > us_signals else "us"


def parse_amount(text, fmt="us"):
    """Parse a numeric amount from text, handling format-specific conventions.
    
    Args:
        text: The captured amount string (may include grouping separators)
        fmt: "us" or "european" - determines how separators are interpreted
    
    US format:  1,234.56 → strip commas → 1234.56
    EU format:  1.234,56 → strip periods, replace comma → 1234.56
    """
    if not text:
        return None
    
    # Strip currency symbols and whitespace (but NOT commas/periods yet)
    cleaned = re.sub(r'[£$€¥\s]', '', text.strip())
    
    if fmt == "european":
        # EU: periods are grouping, comma is decimal
        # "1.234,56" → strip periods → "1234,56" → replace comma → "1234.56"
        cleaned = cleaned.replace('.', '').replace(',', '.')
    else:
        # US: commas are grouping, period is decimal
        # "1,234.56" → strip commas → "1234.56"
        cleaned = cleaned.replace(',', '')
    
    match = re.search(r'(\d+\.?\d*)', cleaned)
    if match:
        try:
            return Decimal(match.group(1))
        except (InvalidOperation, ValueError):
            return None
    return None


def format_amount(d):
    """Format a Decimal amount for CSV output (2 decimal places)."""
    if d is None:
        return "0.00"
    return f"{d:.2f}"


# ── Classification ─────────────────────────────────────────────────────────

def _classify_single_text(text_lower):
    """Classify a single text. Returns (classification, score).

    Uses a scoring system with hard negative overrides:
    1. Hard negatives: explicit disclaimers, receipt/expense/PO/reminder signals
    2. Positive scoring: title matches, content patterns, financial structure
    3. Fallback: structured financial layout detection
    """
    # ── Hard Negative Signals ──

    # Explicit disclaimer
    if re.search(r'not\s+(a\s+)?(tax\s+)?invoice', text_lower):
        return ("other", -100)

    # Receipt indicators (confirms payment already made)
    receipt_signals = 0
    if re.search(r'\breceipt\b', text_lower):
        receipt_signals += 1
    if re.search(r'(card|cash|credit)\s+payment\s+(approved|accepted|confirmed)', text_lower):
        receipt_signals += 1
    if re.search(r'\btotal\s+paid\b', text_lower) or re.search(r'\bamount\s+paid\b', text_lower):
        receipt_signals += 1
    if re.search(r'\bpayment\s+(method|received|confirmed)\b', text_lower):
        receipt_signals += 1
    if receipt_signals >= 2:
        return ("other", -50)

    # Expense/reimbursement indicators
    if re.search(r'expense\s+(reimbursement|report|claim|summary)', text_lower):
        return ("other", -50)
    if re.search(r'reimbursement\s+(summary|form|request)', text_lower):
        return ("other", -50)
    if re.search(r'\bapproved\s+(meals|travel|expenses|lodging)\b', text_lower):
        return ("other", -50)
    if re.search(r'\bemployee\s*:', text_lower) and re.search(r'\bapproved\b', text_lower):
        return ("other", -50)
    if re.search(r'\breclaimable\b', text_lower):
        return ("other", -50)

    # Purchase order indicators
    po_signals = 0
    if re.search(r'\bpurchase\s+order\b', text_lower):
        po_signals += 1
    if re.search(r'\bapproval\s+status\s*:\s*pending\b', text_lower):
        po_signals += 1
    if re.search(r'\bapproved\s+spend\b', text_lower):
        po_signals += 1
    if re.search(r'\brequested\s+total\b', text_lower):
        po_signals += 1
    if po_signals >= 2:
        return ("other", -50)
    if re.search(r'\bpurchase\s+order\b', text_lower) and re.search(r'\bpending\b', text_lower):
        return ("other", -50)

    # Payment reminder indicators
    reminder_signals = 0
    if re.search(r'\bpayment\s+reminder\b', text_lower):
        reminder_signals += 1
    if re.search(r'\boutstanding\s+balance\b', text_lower):
        reminder_signals += 1
    if re.search(r'\bprior\s+(tax|invoice|amount)\b', text_lower):
        reminder_signals += 1
    if re.search(r'\bthis\s+notice\b', text_lower):
        reminder_signals += 1
    if reminder_signals >= 2:
        return ("other", -50)

    # ── Positive Scoring ──

    score = 0

    # Direct title matches (strong signals)
    if re.search(r'\binvoice\b', text_lower):
        score += 3
    if re.search(r'\btax\s+invoice\b', text_lower):
        score += 3
    if re.search(r'\bbilling\s+statement\b', text_lower):
        score += 3
    if re.search(r'\bcharge\s+note\b', text_lower):
        score += 3
    if re.search(r'\bcommercial\s+invoice\b', text_lower):
        score += 3

    # Weaker title matches for documents with less standard markers
    if re.search(r'\bbill\s+from\b', text_lower):
        score += 2
    if re.search(r'\bpayment\s+request\b', text_lower):
        score += 2
    if re.search(r'\bfee\s+(?:schedule|statement|notice)\b', text_lower):
        score += 2
    if re.search(r'\bstatement\s+of\s+(?:charges|fees|account)\b', text_lower):
        score += 2

    # Fuzzy title matches for OCR noise
    if re.search(r'\bcharge\s+n[a-z]{2,4}\b', text_lower):
        score += 2  # "Charge Nate/Nots/Nols" → "Charge Note"
    if re.search(r'\binvo[a-z]{2,4}\b', text_lower) and not re.search(r'\binvoice\b', text_lower):
        score += 2  # "Invoce/Invoio" → "Invoice"

    # Billing document titles
    if re.search(r'\btax\s+document\b', text_lower):
        score += 2
    if re.search(r'\bremittance\s+notice\b', text_lower):
        score += 2
    if re.search(r'\bbill\s+to\b', text_lower):
        score += 2
    if re.search(r'\bstatement\s+ref\b', text_lower):
        score += 1

    # Payment request language
    for pat in [r'\bamount\s+due\b', r'\btotal\s+due\b', r'\bgrand\s+total\b',
                r'\bpayable\s+total\b', r'\bplease\s+remit\b', r'\bbalance\s+due\b']:
        if re.search(pat, text_lower):
            score += 2
    if re.search(r'\bnet\s+charges\b', text_lower):
        score += 1

    # OCR-noisy total due variants
    if re.search(r'\btotal\s+d[uo]e\b', text_lower) and not re.search(r'\btotal\s+due\b', text_lower):
        score += 2

    # Service/item indicators (broadened for weaker markers)
    for pat in [r'\bdesign\s+retainer\b', r'\bconsulting\s+services\b',
                r'\bhardware\s+order\b', r'\bfreight\s+services\b',
                r'\bservices\s+rendered\b', r'\bprofessional\s+fees\b',
                r'\bmanagement\s+fees\b', r'\bsupport\s+charges\b']:
        if re.search(pat, text_lower):
            score += 1
    if re.search(r'\b(ship|bill)\s+to\b', text_lower):
        score += 1
    if re.search(r'\bclient\s*:', text_lower):
        score += 1
    if re.search(r'\bcustomer\s*:', text_lower):
        score += 1
    if re.search(r'\bvendor\s*:', text_lower):
        score += 1
    if re.search(r'\bsupplier\s*:', text_lower):
        score += 1

    # Financial structure signals
    if re.search(r'\bsubtotal\b', text_lower) and re.search(r'\btax\b', text_lower):
        score += 1
    # Check for VAT with amount (format-agnostic: look for VAT/GST near numbers)
    if re.search(r'\bvat\b', text_lower) and (re.search(r'\d+\.\d{2}', text_lower) or re.search(r'\d+,\d{2}', text_lower)):
        score += 1
    # Subtotal presence (indicates structured invoice)
    if re.search(r'\bsubtotal\b', text_lower):
        score += 1
    # "Total:" at line start (indicates invoice total)
    if re.search(r'^\s*total\s*:', text_lower, re.MULTILINE):
        score += 1
    
    # Invoice number/reference patterns (strong signal of invoicing)
    if re.search(r'\binvoice\s*(?:#|no|number|ref)\s*[:#]?\s*[a-z0-9-]+', text_lower):
        score += 2
    if re.search(r'\b(inv|inv-no|inv#)\s*[:#]?\s*[a-z0-9-]+', text_lower):
        score += 2
    # Generic invoice/reference number patterns (e.g., "Rechnungsnr:", "Facture no:")
    if re.search(r'(rechnungsnr|facture\s*no|factuur\s*nr|fattura\s*n)\s*[:#]?\s*[a-z0-9-]+', text_lower):
        score += 2

    # ── Decision ──

    if score >= 4:
        return ("invoice", score)

    # Fallback: structured financial layout (format-agnostic)
    if score >= 2:
        # Count amounts in either US or EU format
        us_amounts = len(re.findall(r'\d+\.\d{2}', text_lower))
        eu_amounts = len(re.findall(r'\d+,\d{2}', text_lower))
        has_amounts = (us_amounts + eu_amounts) >= 2
        has_dates = bool(re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', text_lower))
        has_reference = bool(re.search(r'(ref|reference|number|no\.?|id)\s*[:#]?\s*[a-z0-9-]+', text_lower))
        if has_amounts and (has_dates or has_reference):
            return ("invoice", score)

    return ("other", score)


def classify_document(texts):
    """Classify document from multiple text candidates.

    Classifies each text independently, then uses the maximum invoice score
    across all candidates. This exploits OCR diversity: if ANY OCR pass
    reveals invoice signals that others miss, the document is still classified
    correctly.
    """
    if isinstance(texts, str):
        texts = [texts]

    best_class = "other"
    best_score = -999

    for text in texts:
        text_lower = text.lower()
        cls, score = _classify_single_text(text_lower)
        if score > best_score:
            best_score = score
            best_class = cls

    return best_class


# ── Financial Field Extraction (multi-text) ────────────────────────────────

# Label priority ranks for total amount (lower = higher priority)
TOTAL_LABEL_PRIORITY = {
    "high": 1,    # grand total, amount due, total due, payable total
    "medium": 2,  # invoice total, balance due, total amount, amount payable
    "low": 3,     # generic "total" (tightened to avoid false matches)
}


def _extract_total_from_text(text, fmt="us"):
    """Extract total amount candidates from a single text.

    Returns list of (amount, priority_rank, label_type) tuples.
    """
    candidates = []
    lines = text.split('\n')
    
    # Format-aware amount pattern
    amt = US_AMOUNT if fmt == "us" else EU_AMOUNT

    # High-priority patterns (explicit final-total labels)
    high_patterns = [
        rf'(?:grand\s+total|amount\s+due|total\s+due|payable\s+total)\s*[:\-]?\s*[£$€]?\s*{amt}',
        rf'(?:total\s+d[uo]e|grand\s+t[o0]tal|payable\s+t[o0]tal)\s*[:\-]?\s*[£$€]?\s*{amt}',
        rf'["\u201c]?\s*(?:total|grand\s+total)\s+due\s*[:\-]?\s*[£$€]?\s*{amt}',
    ]

    # Medium-priority patterns
    medium_patterns = [
        rf'(?:invoice\s+total|balance\s+due|total\s+amount|amount\s+payable)\s*[:\-]?\s*[£$€]?\s*{amt}',
    ]

    # Low-priority: generic "total" anchored to line start to avoid matching
    # "Line Total", "subtotal", "total tax", etc.
    low_patterns = [
        rf'^\s*total\s*[:\-]\s*[£$€]?\s*{amt}',
    ]

    for line in lines:
        ll = line.lower().strip()

        for pat in high_patterns:
            m = re.search(pat, ll)
            if m:
                amt_val = parse_amount(m.group(1), fmt)
                if amt_val and amt_val > 0:
                    candidates.append((amt_val, TOTAL_LABEL_PRIORITY["high"], "high"))

        for pat in medium_patterns:
            m = re.search(pat, ll)
            if m:
                amt_val = parse_amount(m.group(1), fmt)
                if amt_val and amt_val > 0:
                    candidates.append((amt_val, TOTAL_LABEL_PRIORITY["medium"], "medium"))

        for pat in low_patterns:
            m = re.search(pat, ll)
            if m:
                amt_val = parse_amount(m.group(1), fmt)
                if amt_val and amt_val > 0:
                    candidates.append((amt_val, TOTAL_LABEL_PRIORITY["low"], "low"))

    return candidates


def _extract_vat_from_text(text, fmt="us"):
    """Extract VAT/tax amount candidates from a single text.

    Returns list of (amount, priority_rank) tuples.
    Priority: explicit VAT/GST with rate > VAT/GST > tax/sales tax > OCR-garbled
    """
    candidates = []
    lines = text.split('\n')
    
    # Format-aware amount pattern
    amt = US_AMOUNT if fmt == "us" else EU_AMOUNT

    # Priority 1: VAT/GST with explicit rate (e.g., "VAT 10%: 128.00")
    p1_patterns = [
        rf'(?:vat|gst)\s+\d+%\s*[:\-]?\s*[£$€]?\s*{amt}',
    ]

    # Priority 2: VAT/GST/Tax with separator
    p2_patterns = [
        rf'(?:vat|gst)\s*[:\-]\s*[£$€]?\s*{amt}',
        rf'(?:tax|sales\s+tax)\s*[:\-]\s*[£$€]?\s*{amt}',
        rf'(?:vat|tax|gst)\s+(?:included|rate)\s*[:\-]?\s*[£$€]?\s*{amt}',
    ]

    # Priority 3: VAT/GST/Tax without separator (OCR-garbled)
    # These need format-specific decimal patterns
    if fmt == "us":
        p3_patterns = [
            r'(?:vat|gst)\s*[£$€]?\s*([\d,]+\.\d{2})',
            r'(?:tax)\s*[£$€]?\s*([\d,]+\.\d{2})',
            # OCR-noisy variants: "@st", "ast", "st." for VAT
            r'[@a]st\.?\s*[£$€]?\s*([\d,]+\.\d{2})',
        ]
    else:
        p3_patterns = [
            r'(?:vat|gst)\s*[£$€]?\s*([\d.]+,\d{2})',
            r'(?:tax)\s*[£$€]?\s*([\d.]+,\d{2})',
            r'[@a]st\.?\s*[£$€]?\s*([\d.]+,\d{2})',
        ]

    # Priority 4: No-decimal OCR fallback (e.g., "ast 7840" → 78.40)
    p4_patterns = [
        r'[@a]st\.?\s*[£$€]?\s*([\d,]{3,})',  # 3+ digits without decimal
    ]

    for line in lines:
        ll = line.lower().strip()

        for pat in p1_patterns:
            m = re.search(pat, ll)
            if m:
                amt_val = parse_amount(m.group(1), fmt)
                if amt_val and amt_val > 0:
                    candidates.append((amt_val, 1))

        for pat in p2_patterns:
            m = re.search(pat, ll)
            if m:
                amt_val = parse_amount(m.group(1), fmt)
                if amt_val and amt_val > 0:
                    candidates.append((amt_val, 2))

        for pat in p3_patterns:
            m = re.search(pat, ll)
            if m:
                amt_val = parse_amount(m.group(1), fmt)
                if amt_val and amt_val > 0:
                    candidates.append((amt_val, 3))

        for pat in p4_patterns:
            m = re.search(pat, ll)
            if m:
                raw = m.group(1).replace(',', '')
                # Interpret as cents: last 2 digits are decimal
                if len(raw) >= 3:
                    integer_part = raw[:-2]
                    decimal_part = raw[-2:]
                    try:
                        amt_val = Decimal(f"{integer_part}.{decimal_part}")
                        if amt_val > 0:
                            candidates.append((amt_val, 4))
                    except (InvalidOperation, ValueError):
                        pass

    return candidates


def _extract_subtotal_from_text(text, fmt="us"):
    """Extract subtotal from a single text. Returns Decimal or None."""
    lines = text.split('\n')
    
    # Format-aware amount pattern
    amt = US_AMOUNT if fmt == "us" else EU_AMOUNT
    
    for line in lines:
        ll = line.lower().strip()
        m = re.search(
            rf'(?:subtotal|sub-total|sub\s*tot|net\s+charges|net\s+amount)\s*[:\-]?\s*[£$€]?\s*{amt}',
            ll
        )
        if m:
            amt_val = parse_amount(m.group(1), fmt)
            if amt_val and amt_val > 0:
                return amt_val
    return None


def _extract_tax_rate_from_text(text):
    """Extract tax rate percentage from text. Returns Decimal (e.g., 10.0 for 10%) or None."""
    lines = text.split('\n')
    for line in lines:
        ll = line.lower().strip()
        # Match patterns like "VAT 10%", "GST 20%", "Tax 15%", "VAT @ 10%"
        m = re.search(r'(?:vat|gst|tax|sales\s+tax)\s*(?:@\s*)?(\d+(?:\.\d+)?)\s*%', ll)
        if m:
            try:
                rate = Decimal(m.group(1))
                if 0 < rate <= 100:  # Sanity check
                    return rate
            except (InvalidOperation, ValueError):
                pass
    return None


def extract_financial_fields(texts):
    """Extract total_amount and vat_amount from multiple text candidates.

    Runs extraction on EVERY candidate text, collects all field values with
    their label priorities, then selects the best value per field using a
    multi-strategy approach:
    
    1. Detect number format (US vs European) from all texts
    2. Collect all candidates for total, VAT, subtotal, and tax rate
    3. Select best total by label priority
    4. Select best VAT by pattern priority
    5. If VAT not found, try: (a) subtotal calculation, (b) rate calculation
    6. Consistency check: prefer total that equals subtotal + VAT when multiple exist
    """
    if isinstance(texts, str):
        texts = [texts]

    # Detect number format once for the entire document
    fmt = detect_number_format(texts)

    all_total_candidates = []   # (amount, priority_rank, label_type)
    all_vat_candidates = []     # (amount, priority_rank)
    all_subtotals = []          # Decimal values
    all_tax_rates = []          # Decimal values (percentages)

    for text in texts:
        # Collect total candidates
        total_cands = _extract_total_from_text(text, fmt)
        all_total_candidates.extend(total_cands)

        # Collect VAT candidates
        vat_cands = _extract_vat_from_text(text, fmt)
        all_vat_candidates.extend(vat_cands)

        # Collect subtotal
        subtotal = _extract_subtotal_from_text(text, fmt)
        if subtotal:
            all_subtotals.append(subtotal)

        # Collect tax rate
        rate = _extract_tax_rate_from_text(text)
        if rate:
            all_tax_rates.append(rate)

    # ── Strategy 1: Direct extraction with consistency check ──
    
    # Select best total by priority
    best_total = None
    if all_total_candidates:
        all_total_candidates.sort(key=lambda x: (x[1], -x[0]))
        best_total = all_total_candidates[0][0]

    # Select best VAT by priority
    best_vat = None
    if all_vat_candidates:
        all_vat_candidates.sort(key=lambda x: (x[1], -x[0]))
        best_vat = all_vat_candidates[0][0]

    # Get best subtotal (most common, or largest if tie)
    best_subtotal = None
    if all_subtotals:
        from collections import Counter
        subtotal_counts = Counter(all_subtotals)
        best_subtotal = subtotal_counts.most_common(1)[0][0]

    # Get most common tax rate
    best_rate = None
    if all_tax_rates:
        from collections import Counter
        rate_counts = Counter(all_tax_rates)
        best_rate = rate_counts.most_common(1)[0][0]

    # ── Strategy 2: Consistency-based selection ──
    # If we have multiple total candidates and subtotal + VAT, prefer the total
    # that matches subtotal + VAT (within rounding tolerance)
    
    if len(all_total_candidates) > 1 and best_subtotal and best_vat:
        expected_total = best_subtotal + best_vat
        tolerance = Decimal('0.02')  # Allow for rounding
        
        for total_cand, priority, _ in all_total_candidates:
            if abs(total_cand - expected_total) <= tolerance:
                best_total = total_cand
                break

    # ── Strategy 3: Fallback calculations for VAT ──
    
    if best_vat is None and best_total is not None:
        # 3a: Calculate from subtotal
        if best_subtotal and best_total > best_subtotal:
            best_vat = (best_total - best_subtotal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # 3b: Calculate from tax rate
        elif best_rate and best_subtotal:
            calculated_vat = (best_subtotal * best_rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            best_vat = calculated_vat
            
            # Recalculate total if it wasn't found or doesn't match
            if best_total is None:
                best_total = best_subtotal + calculated_vat

    return best_total, best_vat


# ── Main Processing ────────────────────────────────────────────────────────

def process_documents():
    """Main entry point: classify, extract, move, and summarize."""

    # Create output directories
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)

    # Collect document files
    doc_files = sorted(
        f for f in DOCS_DIR.iterdir()
        if f.suffix.lower() in SUPPORTED_EXTS and f.is_file()
    )

    invoices = []  # (filename, total_amount, vat_amount)

    for filepath in doc_files:
        print(f"Processing: {filepath.name}")

        # Extract multiple text candidates
        texts = extract_texts(filepath)
        print(f"  Text candidates: {len(texts)}")

        # Classify using all candidates (max score wins)
        classification = classify_document(texts)
        print(f"  Class: {classification}")

        if classification == "invoice":
            # Extract fields from ALL candidates, select best per field
            total_amount, vat_amount = extract_financial_fields(texts)
            print(f"  Total: {total_amount}, VAT: {vat_amount}")

            dest = INVOICES_DIR / filepath.name
            shutil.move(str(filepath), str(dest))

            t = total_amount if total_amount is not None else Decimal('0')
            v = vat_amount if vat_amount is not None else Decimal('0')
            invoices.append((filepath.name, t, v))
        else:
            dest = OTHER_DIR / filepath.name
            shutil.move(str(filepath), str(dest))

    # Write summary CSV
    with open(SUMMARY_PATH, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])

        total_sum = Decimal('0')
        vat_sum = Decimal('0')

        for filename, total, vat in invoices:
            writer.writerow([filename, format_amount(total), format_amount(vat)])
            total_sum += total
            vat_sum += vat

        writer.writerow(['total', format_amount(total_sum), format_amount(vat_sum)])

    print(f"\nDone: {len(invoices)} invoices / {len(doc_files)} documents")
    print(f"Summary: {SUMMARY_PATH}")

    # Verify
    remaining = list(DOCS_DIR.iterdir())
    if remaining:
        print(f"WARNING: {len(remaining)} files still in documents/")
    else:
        print("documents/ is empty ✓")


if __name__ == "__main__":
    process_documents()
