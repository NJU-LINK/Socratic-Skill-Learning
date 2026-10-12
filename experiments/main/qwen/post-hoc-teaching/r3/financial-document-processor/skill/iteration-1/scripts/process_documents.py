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


# ── Amount Parsing ─────────────────────────────────────────────────────────

def parse_amount(text):
    """Parse a numeric amount from text, handling commas and currency symbols."""
    if not text:
        return None
    cleaned = re.sub(r'[£$€¥,\s]', '', text.strip())
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

    # Service/item indicators
    for pat in [r'\bdesign\s+retainer\b', r'\bconsulting\s+services\b',
                r'\bhardware\s+order\b', r'\bfreight\s+services\b',
                r'\bservices\s+rendered\b']:
        if re.search(pat, text_lower):
            score += 1
    if re.search(r'\b(ship|bill)\s+to\b', text_lower):
        score += 1
    if re.search(r'\bclient\s*:', text_lower):
        score += 1
    if re.search(r'\bcustomer\s*:', text_lower):
        score += 1

    # Financial structure signals
    if re.search(r'\bsubtotal\b', text_lower) and re.search(r'\btax\b', text_lower):
        score += 1
    if re.search(r'\bvat\b', text_lower) and re.search(r'\d+\.\d{2}', text_lower):
        score += 1

    # ── Decision ──

    if score >= 4:
        return ("invoice", score)

    # Fallback: structured financial layout
    if score >= 2:
        has_amounts = len(re.findall(r'\d+\.\d{2}', text_lower)) >= 2
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


def _extract_total_from_text(text):
    """Extract total amount candidates from a single text.

    Returns list of (amount, priority_rank, label_type) tuples.
    """
    candidates = []
    lines = text.split('\n')

    # High-priority patterns (explicit final-total labels)
    high_patterns = [
        r'(?:grand\s+total|amount\s+due|total\s+due|payable\s+total)\s*[:\-]?\s*[£$€]?\s*([\d,]+\.?\d*)',
        r'(?:total\s+d[uo]e|grand\s+t[o0]tal|payable\s+t[o0]tal)\s*[:\-]?\s*[£$€]?\s*([\d,]+\.?\d*)',
        r'["\u201c]?\s*(?:total|grand\s+total)\s+due\s*[:\-]?\s*[£$€]?\s*([\d,]+\.?\d*)',
    ]

    # Medium-priority patterns
    medium_patterns = [
        r'(?:invoice\s+total|balance\s+due|total\s+amount|amount\s+payable)\s*[:\-]?\s*[£$€]?\s*([\d,]+\.?\d*)',
    ]

    # Low-priority: generic "total" but tightened to require colon/dash separator
    # and line-start or whitespace boundary to avoid matching "subtotal", "total tax", etc.
    low_patterns = [
        r'(?:^|\s)total\s*[:\-]\s*[£$€]?\s*([\d,]+\.?\d*)',
    ]

    for line in lines:
        ll = line.lower().strip()

        for pat in high_patterns:
            m = re.search(pat, ll)
            if m:
                amt = parse_amount(m.group(1))
                if amt and amt > 0:
                    candidates.append((amt, TOTAL_LABEL_PRIORITY["high"], "high"))

        for pat in medium_patterns:
            m = re.search(pat, ll)
            if m:
                amt = parse_amount(m.group(1))
                if amt and amt > 0:
                    candidates.append((amt, TOTAL_LABEL_PRIORITY["medium"], "medium"))

        for pat in low_patterns:
            m = re.search(pat, ll)
            if m:
                amt = parse_amount(m.group(1))
                if amt and amt > 0:
                    candidates.append((amt, TOTAL_LABEL_PRIORITY["low"], "low"))

    return candidates


def _extract_vat_from_text(text):
    """Extract VAT/tax amount candidates from a single text.

    Returns list of (amount, priority_rank) tuples.
    Priority: explicit VAT/GST with rate > VAT/GST > tax/sales tax > OCR-garbled
    """
    candidates = []
    lines = text.split('\n')

    # Priority 1: VAT/GST with explicit rate (e.g., "VAT 10%: 128.00")
    p1_patterns = [
        r'(?:vat|gst)\s+\d+%\s*[:\-]?\s*[£$€]?\s*([\d,]+\.?\d*)',
    ]

    # Priority 2: VAT/GST/Tax with separator
    p2_patterns = [
        r'(?:vat|gst)\s*[:\-]\s*[£$€]?\s*([\d,]+\.?\d*)',
        r'(?:tax|sales\s+tax)\s*[:\-]\s*[£$€]?\s*([\d,]+\.?\d*)',
        r'(?:vat|tax|gst)\s+(?:included|rate)\s*[:\-]?\s*[£$€]?\s*([\d,]+\.?\d*)',
    ]

    # Priority 3: VAT/GST/Tax without separator (OCR-garbled)
    p3_patterns = [
        r'(?:vat|gst)\s*[£$€]?\s*([\d,]+\.\d{2})',
        r'(?:tax)\s*[£$€]?\s*([\d,]+\.\d{2})',
        # OCR-noisy variants: "@st", "ast", "st." for VAT
        r'[@a]st\.?\s*[£$€]?\s*([\d,]+\.\d{2})',
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
                amt = parse_amount(m.group(1))
                if amt and amt > 0:
                    candidates.append((amt, 1))

        for pat in p2_patterns:
            m = re.search(pat, ll)
            if m:
                amt = parse_amount(m.group(1))
                if amt and amt > 0:
                    candidates.append((amt, 2))

        for pat in p3_patterns:
            m = re.search(pat, ll)
            if m:
                amt = parse_amount(m.group(1))
                if amt and amt > 0:
                    candidates.append((amt, 3))

        for pat in p4_patterns:
            m = re.search(pat, ll)
            if m:
                raw = m.group(1).replace(',', '')
                # Interpret as cents: last 2 digits are decimal
                if len(raw) >= 3:
                    integer_part = raw[:-2]
                    decimal_part = raw[-2:]
                    try:
                        amt = Decimal(f"{integer_part}.{decimal_part}")
                        if amt > 0:
                            candidates.append((amt, 4))
                    except (InvalidOperation, ValueError):
                        pass

    return candidates


def _extract_subtotal_from_text(text):
    """Extract subtotal from a single text. Returns Decimal or None."""
    lines = text.split('\n')
    for line in lines:
        ll = line.lower().strip()
        m = re.search(
            r'(?:subtotal|sub-total|sub\s*tot|net\s+charges|net\s+amount)\s*[:\-]?\s*[£$€]?\s*([\d,]+\.?\d*)',
            ll
        )
        if m:
            amt = parse_amount(m.group(1))
            if amt and amt > 0:
                return amt
    return None


def extract_financial_fields(texts):
    """Extract total_amount and vat_amount from multiple text candidates.

    Runs extraction on EVERY candidate text, collects all field values with
    their label priorities, then selects the best value per field:
    - For total: prefer the match with the highest-priority (most specific) label
    - For VAT: prefer the match with the highest-priority pattern
    - Fallback: calculate VAT from best total - best subtotal
    """
    if isinstance(texts, str):
        texts = [texts]

    all_total_candidates = []   # (amount, priority_rank, label_type)
    all_vat_candidates = []     # (amount, priority_rank)
    all_subtotals = []          # Decimal values

    for text in texts:
        # Collect total candidates
        total_cands = _extract_total_from_text(text)
        all_total_candidates.extend(total_cands)

        # Collect VAT candidates
        vat_cands = _extract_vat_from_text(text)
        all_vat_candidates.extend(vat_cands)

        # Collect subtotal
        subtotal = _extract_subtotal_from_text(text)
        if subtotal:
            all_subtotals.append(subtotal)

    # Select best total: lowest priority rank wins
    total_amount = None
    if all_total_candidates:
        # Sort by priority rank (ascending), then by amount (descending for ties)
        all_total_candidates.sort(key=lambda x: (x[1], -x[0]))
        total_amount = all_total_candidates[0][0]

    # Select best VAT: lowest priority rank wins
    vat_amount = None
    if all_vat_candidates:
        all_vat_candidates.sort(key=lambda x: (x[1], -x[0]))
        vat_amount = all_vat_candidates[0][0]

    # Fallback: calculate VAT from total - subtotal
    if vat_amount is None and total_amount is not None and all_subtotals:
        # Use the most common subtotal, or the one that makes sense
        for subtotal in all_subtotals:
            if total_amount > subtotal:
                vat_amount = (total_amount - subtotal).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                break

    return total_amount, vat_amount


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
