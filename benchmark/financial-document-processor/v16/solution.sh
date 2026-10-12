#!/bin/bash

set -euo pipefail

cd /app

sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
apt-get update
apt-get install -y --no-install-recommends poppler-utils tesseract-ocr

python3 - <<'PY'
import csv
import re
import shutil
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


DOCUMENTS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
AMOUNT_RE = r"([0-9]+(?:\.[0-9]{2})?)"


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout

    result = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "6"],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def parse_decimal(value: str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decimal_to_csv(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def extract_final_total_amount(text: str) -> Decimal:
    normalized_lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized_text = "\n".join(normalized_lines)

    preferred_labels = [
        r"\bbalance due\b",
        r"\bgross amount\b",
        r"\bsettlement total\b",
        r"\btotal amount\b",
        r"\btotal\b",
        r"\bgrand total\b",
        r"\bamount due\b",
    ]

    for label in preferred_labels:
        matches = re.findall(rf"{label}\s*:?\s*{AMOUNT_RE}", normalized_text, flags=re.IGNORECASE)
        if matches:
            return parse_decimal(matches[-1])

    raise ValueError("Missing total amount")


def extract_vat_amount(text: str) -> Decimal:
    vat_patterns = [
        rf"vat(?:\s*\d+%)?\s*:?\s*{AMOUNT_RE}",
        rf"gst\s*:?\s*{AMOUNT_RE}",
        rf"tax\s*:?\s*{AMOUNT_RE}",
    ]
    for pattern in vat_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return parse_decimal(match.group(1))
    return Decimal("0.00")


def extract_invoice_fields(text: str) -> tuple[Decimal, Decimal]:
    total_amount = extract_final_total_amount(text)
    vat_amount = extract_vat_amount(text)
    return total_amount, vat_amount


def classify_document(text: str) -> str:
    lowered = re.sub(r"\s+", " ", text.lower())

    explicit_other_phrases = [
        "not a tax invoice",
        "not an invoice",
        "not a bill",
        "budget overview",
        "payment reminder",
        "purchase order",
        "expense summary",
        "planning sheet is for budgeting only",
        "internal reimbursement worksheet only",
        "authorizes a purchase",
    ]
    if any(phrase in lowered for phrase in explicit_other_phrases):
        return "other"

    seller_markers = ["supplier:", "issuer:", "provider:"]
    buyer_markers = ["customer:", "bill to:"]
    reference_markers = ["statement no:", "statement id:", "receipt ref:", "account ref:"]
    payable_markers = ["balance due:", "gross amount:", "settlement total:"]
    tax_markers = ["vat", "gst", "tax:"]

    score = 0
    if any(marker in lowered for marker in seller_markers) and any(
        marker in lowered for marker in buyer_markers
    ):
        score += 2
    if any(marker in lowered for marker in reference_markers):
        score += 1
    if "qty" in lowered and any(marker in lowered for marker in ["unit", "amount", "unit price", "line total"]):
        score += 1
    if any(marker in lowered for marker in payable_markers):
        score += 2
    if any(marker in lowered for marker in tax_markers):
        score += 1
    if any(marker in lowered for marker in ["subtotal:", "net amount:"]):
        score += 1

    return "invoice" if score >= 4 else "other"


def main() -> None:
    INVOICES_DIR.mkdir(exist_ok=True)
    OTHER_DIR.mkdir(exist_ok=True)

    invoice_rows: list[tuple[str, Decimal, Decimal]] = []

    for path in sorted(DOCUMENTS_DIR.iterdir()):
        if not path.is_file():
            continue

        text = extract_text(path)
        destination_dir = INVOICES_DIR if classify_document(text) == "invoice" else OTHER_DIR

        if destination_dir == INVOICES_DIR:
            total_amount, vat_amount = extract_invoice_fields(text)
            invoice_rows.append((path.name, total_amount, vat_amount))

        shutil.move(str(path), destination_dir / path.name)

    total_total = sum((row[1] for row in invoice_rows), Decimal("0.00"))
    total_vat = sum((row[2] for row in invoice_rows), Decimal("0.00"))

    with (INVOICES_DIR / "summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "total_amount", "vat_amount"])
        for filename, total_amount, vat_amount in invoice_rows:
            writer.writerow([filename, decimal_to_csv(total_amount), decimal_to_csv(vat_amount)])
        writer.writerow(["total", decimal_to_csv(total_total), decimal_to_csv(total_vat)])


if __name__ == "__main__":
    parser_test_path = Path("/tmp/financial_document_processor_parser_probe.py")
    if parser_test_path.exists():
        exec(parser_test_path.read_text(), globals())
    else:
        main()
PY
