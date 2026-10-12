#!/bin/bash
set -euo pipefail

cd /app

cat <<'PY' > /app/process_documents.py
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pillow==11.3.0",
#   "pytesseract==0.3.13",
# ]
# ///

from __future__ import annotations

import csv
import difflib
import re
import shutil
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytesseract
from PIL import Image, ImageOps


DOCUMENTS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
AMOUNT_RE = re.compile(r"([0-9][0-9,\.]*(?:\.\d{2})|[0-9]{3,6})")


@dataclass
class InvoiceRow:
    filename: str
    total_amount: Decimal
    vat_amount: Decimal


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        text = result.stdout
        if pdf_text_is_usable(text):
            return text
        return extract_pdf_text_with_ocr(path)

    with Image.open(path) as image:
        return extract_text_from_image(image)


def extract_text_from_image(image: Image.Image) -> str:
    image = ImageOps.grayscale(image)
    image = ImageOps.autocontrast(image)
    image = image.resize((image.width * 2, image.height * 2))
    image = image.point(lambda value: 0 if value < 180 else 255, mode="1")
    return pytesseract.image_to_string(image, config="--psm 6")


def pdf_text_is_usable(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    return len(normalize_words(text)) >= 8


def extract_pdf_text_with_ocr(path: Path) -> str:
    with TemporaryDirectory() as temp_dir:
        output_prefix = Path(temp_dir) / "page"
        subprocess.run(
            ["pdftoppm", "-r", "200", "-png", str(path), str(output_prefix)],
            check=True,
            capture_output=True,
            text=True,
        )

        page_texts = []
        for image_path in sorted(Path(temp_dir).glob("page-*.png")):
            with Image.open(image_path) as image:
                page_texts.append(extract_text_from_image(image))
        return "\n".join(page_texts)


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def normalize_words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def line_matches_phrase(line: str, phrase: str, cutoff: float = 0.8) -> bool:
    normalized_line = normalize_text(line)
    normalized_phrase = normalize_text(phrase)
    if not normalized_line:
        return False
    if normalized_phrase in normalized_line:
        return True
    return difflib.SequenceMatcher(None, normalized_line, normalized_phrase).ratio() >= cutoff


def has_phrase(lines: list[str], phrases: list[str], cutoff: float = 0.8) -> bool:
    return any(
        line_matches_phrase(line, phrase, cutoff)
        for line in lines
        for phrase in phrases
    )


def count_fields(lines: list[str], labels: list[str], cutoff: float = 0.8) -> int:
    return sum(
        1
        for line in lines
        if any(line_matches_phrase(line, label, cutoff) for label in labels)
    )


def count_item_lines(lines: list[str]) -> int:
    count = 0
    for line in lines:
        lowered = line.lower()
        if not AMOUNT_RE.search(line):
            continue
        if any(
            token in lowered
            for token in ["total", "tax", "vat", "gst", "subtotal", "balance", "amount due"]
        ):
            continue
        if len(normalize_words(line)) >= 2:
            count += 1
    return count


def classify_document(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lowered = "\n".join(line.lower() for line in lines)

    if re.search(r"not\s+a\s+(tax\s+)?invoice", lowered):
        return "other"

    negative_markers = [
        "payment reminder",
        "purchase order",
        "receipt",
        "expense reimbursement summary",
        "approval status",
        "spend ceiling",
        "card payment",
    ]
    if has_phrase(lines, negative_markers, cutoff=0.72):
        return "other"

    if count_fields(lines, ["employee"], cutoff=0.85) and count_fields(lines, ["approved"], cutoff=0.8):
        return "other"

    total_fields = count_fields(
        lines,
        ["amount due", "grand total", "payable total", "total due", "invoice total"],
        cutoff=0.74,
    )
    tax_fields = count_fields(lines, ["vat", "tax", "gst"], cutoff=0.74)
    party_fields = count_fields(
        lines,
        ["bill to", "customer", "client", "ship to", "buyer"],
        cutoff=0.74,
    )
    reference_fields = count_fields(
        lines,
        [
            "invoice number",
            "invoice no",
            "statement ref",
            "reference",
            "doc ref",
            "document id",
            "issue date",
            "issued",
            "service date",
            "dispatch date",
        ],
        cutoff=0.74,
    )
    item_fields = count_item_lines(lines)

    score = 0
    if total_fields:
        score += 2
    if tax_fields:
        score += 2
    if party_fields:
        score += 1
    if reference_fields:
        score += 1
    if item_fields:
        score += 1

    if score >= 5 and total_fields and tax_fields:
        return "invoice"

    if has_phrase(lines, ["invoice", "tax invoice"], cutoff=0.8):
        return "invoice"

    return "other"


def parse_amount_after_label(text: str, labels: list[str]) -> Decimal:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        for label in labels:
            if line_matches_phrase(line, label, cutoff=0.72):
                matches = AMOUNT_RE.findall(line)
                if matches:
                    return normalize_amount(matches[-1])
    raise ValueError(f"missing amount for labels: {labels}")


def normalize_amount(raw: str) -> Decimal:
    cleaned = raw.replace(",", "")
    if cleaned.count(".") > 1:
        whole, decimal = cleaned.rsplit(".", 1)
        cleaned = whole.replace(".", "") + "." + decimal
    elif "." not in cleaned and len(cleaned) >= 3:
        cleaned = cleaned[:-2] + "." + cleaned[-2:]
    return Decimal(cleaned)


def extract_invoice_amounts(text: str) -> tuple[Decimal, Decimal]:
    total = parse_amount_after_label(
        text,
        ["amount due", "grand total", "payable total", "total due", "invoice total"],
    )
    vat = parse_amount_after_label(text, ["vat", "sales tax", "tax", "gst"])
    return total, vat


def format_decimal(value: Decimal) -> str:
    return f"{value:.2f}"


def main() -> None:
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)

    invoice_rows: list[InvoiceRow] = []

    for path in sorted(DOCUMENTS_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".pdf", ".jpg", ".jpeg"}:
            continue

        text = extract_text(path)
        if classify_document(text) == "invoice":
            total_amount, vat_amount = extract_invoice_amounts(text)
            invoice_rows.append(InvoiceRow(path.name, total_amount, vat_amount))
            destination = INVOICES_DIR / path.name
        else:
            destination = OTHER_DIR / path.name

        shutil.move(str(path), destination)

    total_total = sum((row.total_amount for row in invoice_rows), Decimal("0.00"))
    total_vat = sum((row.vat_amount for row in invoice_rows), Decimal("0.00"))

    with (INVOICES_DIR / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "total_amount", "vat_amount"])
        for row in invoice_rows:
            writer.writerow(
                [row.filename, format_decimal(row.total_amount), format_decimal(row.vat_amount)]
            )
        writer.writerow(["total", format_decimal(total_total), format_decimal(total_vat)])


if __name__ == "__main__":
    main()
PY

python3 /app/process_documents.py
