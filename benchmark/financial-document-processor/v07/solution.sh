#!/bin/bash
set -euo pipefail

need_packages=0
for cmd in tesseract; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    need_packages=1
    break
  fi
done

if [ "$need_packages" -eq 1 ]; then
  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y tesseract-ocr
fi

uv run --with pypdf --with pillow python3 - <<'PY'
import csv
import os
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader


APP_ROOT = Path(os.environ.get("APP_ROOT", "/app"))
DOCUMENTS_DIR = APP_ROOT / "documents"
INVOICES_DIR = APP_ROOT / "invoices"
OTHER_DIR = APP_ROOT / "other"
SUMMARY_PATH = INVOICES_DIR / "summary.csv"

MONEY_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})(?!\d)")
RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
TOTAL_LABELS = ["total", "grand total", "amount due", "total payable", "final amount due"]
BASE_LABELS = ["subtotal", "tax basis"]
NON_INVOICE_TERMS = [
    "quotation",
    "quote",
    "estimate",
    "proposal",
    "account statement",
    "statement period",
    "not an invoice",
    "approval only",
]
INVOICE_TERMS = [
    "tax invoice",
    "commercial invoice",
    "invoice",
    "billing notice",
    "client billing",
]


def run_command(*args: str) -> str:
    result = subprocess.run(
        list(args),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = text.replace("|", "1")
    text = text.replace("§", "5")
    text = text.replace("amountdue", "amount due")
    text = text.replace("grandtotal", "grand total")
    text = text.replace("taxrate", "tax rate")
    text = text.replace("salestax", "sales tax")
    text = text.replace("invoiceid", "invoice id")
    text = text.lower()
    return text


def normalized_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in normalize_text(text).splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return lines


def parse_decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def extract_last_money(line: str) -> Decimal | None:
    matches = MONEY_RE.findall(line)
    if not matches:
        return None
    return parse_decimal(matches[-1])


def extract_rate(line: str) -> Decimal | None:
    match = RATE_RE.search(line)
    if not match:
        return None
    return Decimal(match.group(1))


def extract_text_from_pdf(path: Path) -> str:
    parts: list[str] = []
    reader = PdfReader(str(path))

    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            parts.append(page_text)

        for image in getattr(page, "images", []):
            try:
                with Image.open(BytesIO(image.data)) as opened:
                    rendered = opened.convert("RGB")
                    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
                        rendered.save(tmp.name, format="PNG")
                        ocr_text = run_command("tesseract", tmp.name, "stdout", "--psm", "6")
                if ocr_text.strip():
                    parts.append(ocr_text)
            except Exception:
                continue

    return "\n".join(part for part in parts if part.strip())


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_text_from_pdf(path)
    return run_command("tesseract", str(path), "stdout", "--psm", "6")


def classify_document(lines: list[str]) -> str:
    text = "\n".join(lines)
    if any(term in text for term in NON_INVOICE_TERMS):
        return "other"
    if any(term in text for term in INVOICE_TERMS):
        return "invoice"
    has_customer_marker = any(marker in text for marker in ["bill to", "client:", "customer:"])
    has_payment_marker = any(
        marker in text
        for marker in [
            "remit",
            "please pay",
            "pay using",
            "payment terms",
            "release for payment",
            "pay against",
        ]
    )
    has_total_marker = find_total_amount(lines) is not None
    has_tax_marker = find_tax_rate(lines) is not None or find_explicit_vat(lines) is not None or find_labeled_amount(lines, BASE_LABELS) is not None
    if has_total_marker and ((has_customer_marker and has_tax_marker) or (has_customer_marker and has_payment_marker) or (has_tax_marker and has_payment_marker)):
        return "invoice"
    return "other"


def find_labeled_amount(lines: list[str], labels: list[str]) -> Decimal | None:
    for label in labels:
        for line in lines:
            if label in line:
                amount = extract_last_money(line)
                if amount is not None:
                    return amount
    return None


def find_total_amount(lines: list[str]) -> Decimal | None:
    total_amount = None
    for line in lines:
        if line.startswith("total ") or line == "total" or line.startswith("total:"):
            amount = extract_last_money(line)
            if amount is not None:
                total_amount = amount
                break

    if total_amount is not None:
        return total_amount

    for label in ["grand total", "total payable", "final amount due", "amount due"]:
        for line in lines:
            if label in line:
                amount = extract_last_money(line)
                if amount is not None:
                    return amount
    return None


def find_tax_rate(lines: list[str]) -> Decimal | None:
    for line in lines:
        if "tax rate" in line or "sales tax" in line:
            rate = extract_rate(line)
            if rate is not None:
                return rate
    return None


def find_explicit_vat(lines: list[str]) -> Decimal | None:
    for line in lines:
        if "vat" in line or "gst" in line or "tax amount" in line:
            amount = extract_last_money(line)
            if amount is not None:
                return amount
        if "sales tax" in line and "%" not in line:
            amount = extract_last_money(line)
            if amount is not None:
                return amount
        if "tax" in line and all(exclusion not in line for exclusion in ["tax rate", "tax basis", "sales tax"]) and "%" not in line:
            amount = extract_last_money(line)
            if amount is not None:
                return amount
    return None


def compute_vat(lines: list[str], total_amount: Decimal) -> Decimal:
    explicit_vat = find_explicit_vat(lines)
    if explicit_vat is not None:
        return explicit_vat.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    base_amount = find_labeled_amount(lines, BASE_LABELS)
    tax_rate = find_tax_rate(lines)

    if base_amount is not None and total_amount is not None:
        difference = total_amount - base_amount
        if difference >= Decimal("0"):
            return difference.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if base_amount is not None and tax_rate is not None:
        return (base_amount * tax_rate / Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    if tax_rate is not None and total_amount is not None:
        return (total_amount * tax_rate / (Decimal("100") + tax_rate)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    return Decimal("0.00")


def format_amount(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


INVOICES_DIR.mkdir(parents=True, exist_ok=True)
OTHER_DIR.mkdir(parents=True, exist_ok=True)

invoice_rows: list[tuple[str, Decimal, Decimal]] = []

for path in sorted(DOCUMENTS_DIR.iterdir()):
    if not path.is_file():
        continue

    lines = normalized_lines(extract_text(path))
    kind = classify_document(lines)

    if kind == "invoice":
        total_amount = find_total_amount(lines)
        if total_amount is None:
            raise SystemExit(f"Could not determine total amount for {path.name}")
        vat_amount = compute_vat(lines, total_amount)
        invoice_rows.append((path.name, total_amount, vat_amount))
        destination = INVOICES_DIR / path.name
    else:
        destination = OTHER_DIR / path.name

    shutil.move(str(path), destination)

invoice_rows.sort(key=lambda row: row[0])
total_amount_sum = sum((row[1] for row in invoice_rows), start=Decimal("0.00"))
vat_amount_sum = sum((row[2] for row in invoice_rows), start=Decimal("0.00"))

with SUMMARY_PATH.open("w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["filename", "total_amount", "vat_amount"])
    for filename, total_amount, vat_amount in invoice_rows:
        writer.writerow([filename, format_amount(total_amount), format_amount(vat_amount)])
    writer.writerow(["total", format_amount(total_amount_sum), format_amount(vat_amount_sum)])
PY
