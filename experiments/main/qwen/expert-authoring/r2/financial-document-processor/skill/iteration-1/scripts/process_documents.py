#!/usr/bin/env python3
"""
Financial Document Processor
=============================
Classifies a mixed batch of PDFs and images as invoice / other, extracts
total_amount and vat_amount from invoices, moves files into output folders,
and writes a summary CSV.

Requires system tools: pdftotext, tesseract, convert (ImageMagick).
Uses only the Python standard library.
"""

import csv
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOCS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp"}
PDF_EXTENSION = ".pdf"

# OCR preprocessing configs: (convert_args, tesseract_psm)
OCR_CONFIGS = [
    (["-resize", "200%", "-sharpen", "0x1"], 6),
    (["-resize", "250%", "-sharpen", "0x2"], 6),
    (["-resize", "200%", "-contrast", "-sharpen", "0x1"], 6),
]

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_pdf_text(filepath: Path) -> list[str]:
    """Return [text] from a PDF.  Falls back to OCR if embedded text is thin."""
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", str(filepath), "-"],
            capture_output=True, text=True, timeout=30,
        )
        text = r.stdout.strip()
    except Exception:
        text = ""

    if len(text) > 20:
        return [text]

    # Scanned PDF -> render pages to images and OCR
    texts = []
    with tempfile.TemporaryDirectory() as td:
        try:
            subprocess.run(
                ["pdftoppm", "-jpeg", "-r", "300", str(filepath), f"{td}/page"],
                capture_output=True, timeout=60,
            )
            for page_img in sorted(Path(td).glob("*.jpg")):
                for ocr_text in _ocr_image_configs(page_img):
                    texts.append(ocr_text)
        except Exception:
            pass

    return texts if texts else [text]


def extract_image_texts(filepath: Path) -> list[str]:
    """Return a list of OCR texts from multiple preprocessing configs."""
    return _ocr_image_configs(filepath)


def _ocr_image_configs(filepath: Path) -> list[str]:
    texts = []
    for convert_args, psm in OCR_CONFIGS:
        text = _run_ocr(filepath, convert_args, psm)
        if text:
            texts.append(text)
    # Unprocessed fallback
    text = _run_ocr(filepath, [], 6)
    if text:
        texts.append(text)
    return texts or [""]


def _run_ocr(filepath: Path, convert_args: list[str], psm: int) -> str:
    tmpfile = None
    try:
        if convert_args:
            tmpfile = tempfile.mktemp(suffix=".jpg")
            cmd = ["convert", str(filepath)] + convert_args + [tmpfile]
            subprocess.run(cmd, capture_output=True, timeout=30)
            target = tmpfile
        else:
            target = str(filepath)

        r = subprocess.run(
            ["tesseract", target, "stdout", "--psm", str(psm)],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip()
    except Exception:
        return ""
    finally:
        if tmpfile and os.path.exists(tmpfile):
            os.unlink(tmpfile)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_invoice(text: str) -> bool:
    """Score-based invoice classifier.  Returns True if score >= 3."""
    if not text:
        return False

    t = _clean_for_classification(text)
    score = 0

    # --- Positive signals ---
    if re.search(r"\binvoice\b", t):                        score += 4
    if re.search(r"\breceipt\b", t) or re.search(r"recei[gpct]{1,3}\b", t):
                                                             score += 3
    if re.search(r"\bbilling\s*statement\b", t):             score += 3
    if re.search(r"\bcharge\s*not[ea]\b", t) or re.search(r"charge\s*not[es]\b", t):
                                                             score += 3
    if re.search(r"\bremittance\b", t):                      score += 2
    if re.search(r"\btax\s*document\b", t):                  score += 2

    if re.search(r"(?:grand|payable|net)\s*total", t):       score += 2
    if re.search(r"total\s*(?:due|net|payable|paid)", t):    score += 2
    if re.search(r"to[ta]l?\s*(?:due|net|payable|paid)", t): score += 2
    if re.search(r"amount\s*(?:due|payable)", t):            score += 2

    if re.search(r"(?:vat|gst|sales\s*tax)\b.*\d", t):      score += 1
    if re.search(r"\btax\b.*\d", t):                         score += 1

    # --- Negative signals ---
    if re.search(r"not\s*(?:a\s*)?(?:tax\s*)?invoice", t):   score -= 6
    if re.search(r"purchase\s*order", t):                    score -= 4
    if re.search(r"payment\s*reminder", t):                  score -= 4
    if re.search(r"expense\s*reimbursement", t):             score -= 4
    if re.search(r"approval\s*status", t):                   score -= 3
    if re.search(r"reclaimable\s*tax", t):                   score -= 3
    if re.search(r"\bpending\b", t):                         score -= 2
    if re.search(r"estimated\s*tax", t):                     score -= 2
    if re.search(r"requested\s*total", t):                   score -= 2
    if re.search(r"spend\s*ceiling", t):                     score -= 2
    if re.search(r"outstanding\s*balance", t):               score -= 2

    return score >= 3


def _clean_for_classification(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        cleaned = re.sub(r"^[^\w]+", "", line.strip())
        if cleaned:
            lines.append(cleaned)
    return " ".join(lines).lower()


# ---------------------------------------------------------------------------
# Number parsing helpers
# ---------------------------------------------------------------------------

def _parse_num(raw: str) -> float | None:
    """Parse a number string.  Handles commas and multiple dots."""
    s = raw.strip().replace(",", "")
    if not s:
        return None
    # Multiple dots -> keep only last as decimal separator
    if s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except ValueError:
        return None


def _needs_decimal_fix(raw: str) -> bool:
    """True if the raw number string has no decimal point and looks like
    a monetary amount that lost its decimal during OCR."""
    cleaned = raw.strip().replace(",", "")
    if "." in cleaned:
        return False
    try:
        val = float(cleaned)
    except ValueError:
        return False
    # Only fix integers with 3+ digits (>=100)
    return val >= 100 and val == int(val)


def _apply_fix(raw: str, val: float) -> float:
    """Apply decimal fix if needed."""
    if _needs_decimal_fix(raw):
        return val / 100.0
    return val


def _clean_line(line: str) -> str:
    """Strip leading OCR artefacts from a line."""
    return re.sub(r"^[^\w]+", "", line.strip())


def _numbers_on_line(line: str) -> list[float]:
    """Extract monetary numbers from a line, applying decimal fix where
    the raw token has no decimal point."""
    results = []
    for m in re.finditer(r"[\d,]+(?:\.\d+)*", line):
        raw = m.group()
        val = _parse_num(raw)
        if val is not None and val > 0:
            results.append(_apply_fix(raw, val))
    return results


def _numbers_on_line_no_pct(line: str) -> list[float]:
    """Like _numbers_on_line but skips percentage values."""
    results = []
    for m in re.finditer(r"([\d,]+(?:\.\d+)*)\s*(%?)", line):
        if m.group(2) == "%":
            continue
        raw = m.group(1)
        val = _parse_num(raw)
        if val is not None and val > 0:
            results.append(_apply_fix(raw, val))
    return results


# ---------------------------------------------------------------------------
# Amount extraction
# ---------------------------------------------------------------------------

def extract_amounts(texts: list[str]):
    """
    Try each OCR text, extract total/vat candidates, verify arithmetic,
    and return the (total, vat) pair with the best consistency.
    """
    all_candidates = []

    for text in texts:
        total_cands = _total_candidates(text)
        vat_cands = _vat_candidates(text)
        subtotal = _explicit_subtotal(text)

        # Aggressive subtotal inference if explicit one not found
        if subtotal is None and total_cands:
            subtotal = _infer_subtotal(text, total_cands[0], set(vat_cands))

        for t in total_cands:
            for v in vat_cands:
                if t <= v:
                    continue
                if subtotal is not None:
                    error = abs(t - subtotal - v)
                else:
                    error = 0.0
                all_candidates.append((t, v, error))

    if all_candidates:
        all_candidates.sort(key=lambda x: x[2])
        best = all_candidates[0]
        return best[0], best[1]

    # --- Arithmetic fallback ---
    for text in texts:
        total_cands = _total_candidates(text)
        for t in total_cands:
            v = _find_vat_arithmetic(text, t)
            if v is not None:
                return t, v

    # Last resort
    for text in texts:
        total_cands = _total_candidates(text)
        vat_cands = _vat_candidates(text)
        if total_cands and vat_cands:
            return total_cands[0], vat_cands[0]
        if total_cands:
            return total_cands[0], None

    return None, None


# ---- per-field extraction --------------------------------------------------

def _total_candidates(text: str) -> list[float]:
    """Return candidate total amounts, largest first."""
    cands = set()
    for line in text.split("\n"):
        cl = _clean_line(line)
        if _is_total_line(cl):
            for num in _numbers_on_line(cl):
                if num > 0:
                    cands.add(num)
    return sorted(cands, reverse=True)


def _vat_candidates(text: str) -> list[float]:
    """Return candidate tax/VAT amounts, smallest first."""
    cands = set()
    for line in text.split("\n"):
        cl = _clean_line(line)
        if _is_tax_line(cl):
            for num in _numbers_on_line_no_pct(cl):
                if num > 0:
                    cands.add(num)
    return sorted(cands)


def _explicit_subtotal(text: str) -> float | None:
    for line in text.split("\n"):
        cl = _clean_line(line)
        if _is_subtotal_line(cl):
            nums = _numbers_on_line(cl)
            if nums:
                return max(nums)
    return None


def _infer_subtotal(text: str, total: float, vat_set: set[float]) -> float | None:
    """Find the largest monetary amount that looks like a subtotal
    (between 30%-100% of total, not the total or tax)."""
    candidates = []
    for line in text.split("\n"):
        cl = _clean_line(line)
        if _is_total_line(cl) or _is_tax_line(cl):
            continue
        for num in _numbers_on_line(cl):
            if 0 < num < total and num not in vat_set:
                if 0.3 * total <= num <= total:
                    candidates.append(num)
    return max(candidates) if candidates else None


# ---- line predicates -------------------------------------------------------

def _is_total_line(line: str) -> bool:
    t = line.lower()
    # Exclude subtotal lines
    if _is_subtotal_line(line):
        return False
    if re.search(r"(?:grand|payable|net)\s*total", t):
        return True
    if re.search(r"total\s*(?:due|net|payable|paid|pai|pat)", t):
        return True
    if re.search(r"to[ta]a?l?\s*(?:due|net|payable|paid|pai|pat)", t):
        return True  # OCR-tolerant: "Toal Due", "Total Pai"
    if re.search(r"amount\s*(?:due|payable)", t):
        return True
    # General: any line with a "total"-like word and a monetary number
    if re.search(r"\bto[ta]a?l?\b", t) and re.search(r"\d", t):
        return True
    return False


def _is_tax_line(line: str) -> bool:
    t = line.lower()
    # Exclude non-actual tax references
    if re.search(r"estimated|prior|reclaimable|approx", t):
        return False
    if re.search(r"tax\s*(?:document|ref|id|number|form)", t):
        return False
    # Match actual tax lines (must contain a number)
    if not re.search(r"\d", t):
        return False
    if re.search(r"\bvat\b", t):
        return True
    if re.search(r"\bgst\b", t):
        return True
    if re.search(r"sales\s*tax", t):
        return True
    if re.search(r"\btax\b", t):
        return True
    return False


def _is_subtotal_line(line: str) -> bool:
    t = line.lower()
    # OCR-tolerant: "subtotal", "sublotat", "subtoat", "subtotat" etc.
    # All start with "sub" and contain a number
    if t.startswith("sub") and re.search(r"\d", t):
        return True
    if re.search(r"net\s*charges", t) and re.search(r"\d", t):
        return True
    return False


# ---- arithmetic fallback ---------------------------------------------------

def _find_vat_arithmetic(text: str, total: float) -> float | None:
    """Find VAT by looking for two numbers that sum to total."""
    all_nums = set()
    for line in text.split("\n"):
        cl = _clean_line(line)
        if _is_total_line(cl):
            continue
        for num in _numbers_on_line(cl):
            if 0 < num < total:
                all_nums.add(num)

    nums = sorted(all_nums)
    best_vat = None
    best_err = float("inf")

    for n in nums:
        expected_vat = round(total - n, 2)
        if expected_vat <= 0 or expected_vat >= total:
            continue
        for m in nums:
            err = abs(m - expected_vat)
            if err < 0.05 and err < best_err:
                best_err = err
                best_vat = m

    return best_vat


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def setup_dirs():
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)


def find_documents() -> list[Path]:
    docs = []
    if not DOCS_DIR.exists():
        return docs
    for f in sorted(DOCS_DIR.iterdir()):
        ext = f.suffix.lower()
        if ext == PDF_EXTENSION or ext in IMAGE_EXTENSIONS:
            docs.append(f)
    return docs


def move_file(src: Path, dst: Path):
    shutil.move(str(src), str(dst))


# ---------------------------------------------------------------------------
# Summary CSV
# ---------------------------------------------------------------------------

def write_summary_csv(rows: list[dict]):
    csv_path = INVOICES_DIR / "summary.csv"
    total_sum = sum(r["total_amount"] or 0 for r in rows)
    vat_sum = sum(r["vat_amount"] or 0 for r in rows)

    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filename", "total_amount", "vat_amount"])
        for r in rows:
            w.writerow([
                r["filename"],
                f'{r["total_amount"]:.2f}' if r["total_amount"] is not None else "",
                f'{r["vat_amount"]:.2f}' if r["vat_amount"] is not None else "",
            ])
        w.writerow(["total", f"{total_sum:.2f}", f"{vat_sum:.2f}"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    setup_dirs()
    docs = find_documents()
    if not docs:
        print("No documents found in", DOCS_DIR)
        write_summary_csv([])
        return

    invoice_rows = []

    for doc in docs:
        print(f"Processing: {doc.name}")

        ext = doc.suffix.lower()
        if ext == PDF_EXTENSION:
            texts = extract_pdf_text(doc)
        else:
            texts = extract_image_texts(doc)

        # Classify using the best (first non-empty) text
        primary_text = next((t for t in texts if t), "")
        is_invoice = classify_invoice(primary_text)

        if is_invoice:
            total, vat = extract_amounts(texts)
            print(f"  -> Invoice  total={total}  vat={vat}")
            invoice_rows.append({
                "filename": doc.name,
                "total_amount": total,
                "vat_amount": vat,
            })
            move_file(doc, INVOICES_DIR / doc.name)
        else:
            print(f"  -> Other")
            move_file(doc, OTHER_DIR / doc.name)

    write_summary_csv(invoice_rows)

    inv_count = len(invoice_rows)
    oth_count = len(docs) - inv_count
    print(f"\nDone. {inv_count} invoice(s), {oth_count} other. "
          f"Summary: {INVOICES_DIR / 'summary.csv'}")


if __name__ == "__main__":
    main()
