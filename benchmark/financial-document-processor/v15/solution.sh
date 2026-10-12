#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import csv
import re
import shutil
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


DOCS_DIR = Path("/app/documents")
INVOICES_DIR = Path("/app/invoices")
OTHER_DIR = Path("/app/other")
SUMMARY_PATH = INVOICES_DIR / "summary.csv"

MONEY = re.compile(r"\b\d+\.\d{2}\b")
INVOICE_HINTS = (
    "receipt",
    "sales ticket",
    "service summary",
    "balance due",
    "grand total",
    "please remit",
    "payment terms",
)
NEGATIVE_HINTS = (
    "not a bill",
    "no balance is due",
    "no payment is requested",
    "internal notice",
    "supplier letter",
)


def to_money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    result = subprocess.run(
        ["tesseract", str(path), "stdout"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def is_invoice(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in NEGATIVE_HINTS):
        return False
    return any(phrase in lowered for phrase in INVOICE_HINTS)


def extract_amount(text: str, labels: tuple[str, ...]) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lowered_lines = [line.lower() for line in lines]
    for label in labels:
        for index, lowered in enumerate(lowered_lines):
            if label in lowered:
                for original in lines[index:index + 4]:
                    matches = MONEY.findall(original)
                    if matches:
                        return matches[-1]
    return ""


def process() -> None:
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, Decimal, Decimal]] = []
    for path in sorted(p for p in DOCS_DIR.iterdir() if p.is_file()):
        text = extract_text(path)
        destination_dir = INVOICES_DIR if is_invoice(text) else OTHER_DIR
        destination = destination_dir / path.name
        shutil.move(str(path), str(destination))

        if destination_dir == INVOICES_DIR:
            total_amount = extract_amount(text, ("grand total", "balance due", "total"))
            vat_amount = extract_amount(text, ("gst", "tax", "vat")) or "0"
            if not total_amount:
                raise SystemExit(f"Could not extract total amount from {path.name}")
            rows.append((path.name, Decimal(total_amount), Decimal(vat_amount)))

    total_total = sum((row[1] for row in rows), Decimal("0"))
    total_vat = sum((row[2] for row in rows), Decimal("0"))

    with SUMMARY_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "total_amount", "vat_amount"])
        for filename, total_amount, vat_amount in rows:
            writer.writerow([filename, to_money(total_amount), to_money(vat_amount)])
        writer.writerow(["total", to_money(total_total), to_money(total_vat)])


process()
PY
