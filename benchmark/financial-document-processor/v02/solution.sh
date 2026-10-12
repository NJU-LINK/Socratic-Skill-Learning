#!/bin/bash
set -euo pipefail

cd /app

cat > /app/document_processor.py <<'PY'
#!/usr/bin/env python3

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageOps


INVOICE_HINTS = [
    "account number",
    "billing period",
    "service address",
    "payment stub",
    "please include the payment stub",
    "detach and return this payment stub",
    "remittance",
    "payment due date",
    "due date",
    "monthly service statement",
    "customer statement",
    "residential service statement",
    "service statement",
    "current charges",
]

OTHER_HINTS = [
    "for your records only",
    "is not a bill",
    "do not send payment",
    "account summary",
    "courtesy account notice",
    "policy update letter",
    "rate change notice",
    "not a payment coupon",
    "informational",
]

TOTAL_PRIORITY_PATTERNS = [
    r"grand\s+total\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
    r"total\s*(?:amount)?\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
]

PAYABLE_TOTAL_PATTERNS = [
    *TOTAL_PRIORITY_PATTERNS,
    r"total\s+due\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
    r"amount\s+due\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
    r"balance\s+due\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
]

VAT_PATTERNS = [
    r"sales\s+tax\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
    r"municipal\s+tax\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
    r"gst\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
    r"vat\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
    r"tax\s*[:$]\s*\$?\s*([0-9][0-9,]*\.\d{2})",
]


def normalize_amount(value: str) -> float:
    return float(value.replace(",", ""))


def normalize_text(text: str) -> str:
    text = text.replace("|", "I")
    text = re.sub(r"\$\s+", "$", text)
    text = re.sub(r"([A-Za-z])\$", r"\1 $", text)
    return re.sub(r"\s+", " ", text).strip()


def preprocess_image(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    autocontrast = ImageOps.autocontrast(grayscale)
    return autocontrast.point(lambda px: 255 if px > 180 else 0)


def ocr_image(image: Image.Image) -> str:
    variants = [image, ImageOps.autocontrast(ImageOps.grayscale(image)), preprocess_image(image)]
    texts: list[str] = []
    for variant in variants:
        for config in ("--psm 6", "--psm 11"):
            text = pytesseract.image_to_string(variant, config=config).strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def extract_text_from_image(path: Path) -> str:
    with Image.open(path) as image:
        return ocr_image(image)


def extract_text_from_pdf(path: Path) -> str:
    chunks: list[str] = []
    with fitz.open(path) as document:
        for page in document:
            text = page.get_text("text").strip()
            if text:
                chunks.append(text)
                continue

            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            ocr_text = ocr_image(image)
            if ocr_text:
                chunks.append(ocr_text)

    return "\n".join(chunks).strip()


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}:
        return extract_text_from_image(path)
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    return ""


def classify_document(text: str) -> str:
    lowered = text.lower()

    if any(hint in lowered for hint in OTHER_HINTS):
        return "other"

    invoice_score = sum(hint in lowered for hint in INVOICE_HINTS)
    has_total = any(re.search(pattern, lowered, re.IGNORECASE) for pattern in PAYABLE_TOTAL_PATTERNS)
    has_tax = any(re.search(pattern, lowered, re.IGNORECASE) for pattern in VAT_PATTERNS)
    has_account = any(token in lowered for token in ("account number", "member number", "loan reference"))
    has_service = any(token in lowered for token in ("service address", "billing period", "monthly service statement", "customer statement"))
    asks_for_payment = any(token in lowered for token in ("payment stub", "remittance", "due date", "amount due", "balance due", "total due"))

    if has_total and invoice_score >= 2:
        return "invoice"
    if has_total and has_tax and "due" in lowered:
        return "invoice"
    if has_total and has_account and has_service:
        return "invoice"
    if has_total and asks_for_payment and (has_service or invoice_score >= 1):
        return "invoice"
    if invoice_score >= 3 and (has_tax or "current charges" in lowered or asks_for_payment):
        return "invoice"
    return "other"


def find_first_amount(text: str, patterns: list[str]) -> float | str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalize_amount(match.group(1))
    return ""


def find_total_amount(text: str) -> float | str:
    # If an explicit Total or Grand Total exists, prefer it over Amount Due.
    prioritized = find_first_amount(text, TOTAL_PRIORITY_PATTERNS)
    if prioritized != "":
        return prioritized
    return find_first_amount(text, PAYABLE_TOTAL_PATTERNS)


@dataclass
class Result:
    filename: str
    total_amount: float | str
    vat_amount: float | str


def main() -> None:
    documents_dir = Path("/app/documents")
    invoices_dir = Path("/app/invoices")
    other_dir = Path("/app/other")
    invoices_dir.mkdir(exist_ok=True)
    other_dir.mkdir(exist_ok=True)

    results: list[Result] = []

    for path in sorted(documents_dir.iterdir()):
        if not path.is_file():
            continue

        text = extract_text(path)
        normalized = normalize_text(text)
        doc_type = classify_document(normalized)

        destination = invoices_dir if doc_type == "invoice" else other_dir
        path.rename(destination / path.name)

        if doc_type == "invoice":
            total_amount = find_total_amount(normalized)
            vat_amount = find_first_amount(normalized, VAT_PATTERNS)
            if vat_amount == "":
                vat_amount = 0
            results.append(Result(path.name, total_amount, vat_amount))

    total_total = 0.0
    total_vat = 0.0
    with (invoices_dir / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "total_amount", "vat_amount"])
        for result in results:
            writer.writerow([result.filename, result.total_amount, result.vat_amount])
            if isinstance(result.total_amount, (int, float)):
                total_total += float(result.total_amount)
            if isinstance(result.vat_amount, (int, float)):
                total_vat += float(result.vat_amount)
        writer.writerow(["total", round(total_total, 2), round(total_vat, 2)])


if __name__ == "__main__":
    main()
PY

python3 /app/document_processor.py
