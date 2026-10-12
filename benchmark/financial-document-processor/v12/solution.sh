#!/bin/bash
set -euo pipefail

export APP_ROOT="${APP_ROOT:-/app}"

run_solver() {
  "$@" <<'PY'
import csv
import os
import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path


APP_ROOT = Path(os.environ["APP_ROOT"])
DOCUMENTS_DIR = APP_ROOT / "documents"
INVOICES_DIR = APP_ROOT / "invoices"
OTHER_DIR = APP_ROOT / "other"
SUMMARY_PATH = INVOICES_DIR / "summary.csv"
MONEY_RE = re.compile(r"(?<!\d)(?:USD\s*)?\$?\s*([0-9][0-9,]*\.\d{2})\b")
OCR_READER = None


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def parse_amount(text: str) -> Decimal | None:
    matches = MONEY_RE.findall(text)
    if not matches:
        return None
    return Decimal(matches[-1].replace(",", ""))


def extract_pdf_text(path: Path) -> str:
    if shutil.which("pdftotext"):
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_image_text(path: Path) -> str:
    global OCR_READER

    if shutil.which("tesseract"):
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "--psm", "6"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    import easyocr

    if OCR_READER is None:
        OCR_READER = easyocr.Reader(["en"], gpu=False, verbose=False)
    return "\n".join(OCR_READER.readtext(str(path), detail=0, paragraph=False))


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix in {".jpg", ".jpeg", ".png"}:
        return extract_image_text(path)
    raise SystemExit(f"Unsupported document type: {path.name}")


def classify_document(text: str) -> str:
    lowered = text.lower()
    other_markers = [
        "account reminder",
        "reminder",
        "packing slip",
        "dispatch summary",
        "shipment reference",
        "receiving copy",
        "purchase order",
        "service authorization",
        "approval only",
        "approved ceiling",
    ]
    invoice_markers = [
        "invoice",
        "bill to",
        "billing summary",
        "service statement",
        "job billing",
        "customer copy",
    ]

    if any(marker in lowered for marker in other_markers):
        return "other"
    if any(marker in lowered for marker in invoice_markers):
        return "invoice"
    if "total" in lowered and any(token in lowered for token in ["tax", "vat", "gst"]):
        return "invoice"
    return "other"


def extract_invoice_fields(text: str) -> tuple[Decimal, Decimal]:
    total_candidates: list[Decimal] = []
    amount_due_candidates: list[Decimal] = []
    tax_candidates: list[Decimal] = []

    for raw_line in text.splitlines():
        line = normalize_line(raw_line)
        if not line:
            continue
        lowered = line.lower()
        amount = parse_amount(line)
        if amount is None:
            continue

        if any(token in lowered for token in ["tax", "vat", "gst"]):
            tax_candidates.append(amount)
        if "amount due" in lowered:
            amount_due_candidates.append(amount)
        if "total" in lowered and "subtotal" not in lowered:
            total_candidates.append(amount)

    total_amount = total_candidates[-1] if total_candidates else None
    if total_amount is None and amount_due_candidates:
        total_amount = amount_due_candidates[-1]
    if total_amount is None:
        raise SystemExit("Could not determine invoice total from document text")

    vat_amount = tax_candidates[-1] if tax_candidates else Decimal("0")
    return total_amount, vat_amount


def fmt(amount: Decimal) -> str:
    return f"{amount:.2f}"


INVOICES_DIR.mkdir(parents=True, exist_ok=True)
OTHER_DIR.mkdir(parents=True, exist_ok=True)

invoice_rows = []
total_amount_sum = Decimal("0")
vat_amount_sum = Decimal("0")

for path in sorted(item for item in DOCUMENTS_DIR.iterdir() if item.is_file()):
    text = extract_text(path)
    kind = classify_document(text)
    destination_dir = INVOICES_DIR if kind == "invoice" else OTHER_DIR
    destination = destination_dir / path.name
    shutil.move(str(path), str(destination))

    if kind == "invoice":
        total_amount, vat_amount = extract_invoice_fields(text)
        invoice_rows.append(
            {
                "filename": destination.name,
                "total_amount": fmt(total_amount),
                "vat_amount": fmt(vat_amount),
            }
        )
        total_amount_sum += total_amount
        vat_amount_sum += vat_amount

with SUMMARY_PATH.open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=["filename", "total_amount", "vat_amount"])
    writer.writeheader()
    for row in sorted(invoice_rows, key=lambda item: item["filename"]):
        writer.writerow(row)
    writer.writerow(
        {
            "filename": "total",
            "total_amount": fmt(total_amount_sum),
            "vat_amount": fmt(vat_amount_sum),
        }
    )
PY
}


if command -v pdftotext >/dev/null 2>&1 && command -v tesseract >/dev/null 2>&1; then
  run_solver python3
  exit 0
fi

if [ "$(id -u)" = "0" ]; then
  if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  fi
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y poppler-utils tesseract-ocr
  run_solver python3
  exit 0
fi

run_solver uv run --with pypdf --with easyocr python
