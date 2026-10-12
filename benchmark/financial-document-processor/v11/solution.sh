#!/bin/bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

if ! command -v pdftotext >/dev/null 2>&1 || ! command -v tesseract >/dev/null 2>&1; then
  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  apt-get update
  apt-get install -y poppler-utils tesseract-ocr
fi

mkdir -p /app/invoices /app/other

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

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

AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})*|\d+)\.\d{2}(?!\d)")


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        proc = subprocess.run(
            ["pdftotext", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout

    proc = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "6"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def normalize_amount(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def format_amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def line_amounts(line: str) -> list[Decimal]:
    values: list[Decimal] = []
    for raw in AMOUNT_RE.findall(line):
        values.append(normalize_amount(raw))
    if values:
        return values
    for raw in re.findall(r"(?<![A-Za-z0-9])([0-9][0-9,.,]{2,})(?![A-Za-z0-9])", line):
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 3:
            values.append(Decimal(f"{int(digits[:-2])}.{digits[-2:]}"))
    return values


def find_line_amount(lines: list[str], pattern: str) -> Decimal | None:
    matcher = re.compile(pattern, re.IGNORECASE)
    for index, line in enumerate(lines):
        if matcher.search(line):
            for candidate_line in lines[index:index + 4]:
                values = line_amounts(candidate_line)
                if values:
                    return values[-1]
    return None

def is_invoice(text: str) -> bool:
    lowered = text.lower()
    lines = [line.strip() for line in lowered.splitlines() if line.strip()]

    explicit_non_invoice_patterns = [
        r"not\s+(?:a\s+)?bill",
        r"not\s+(?:an\s+)?invoice",
        r"do\s+not\s+pay",
        r"no\s+payment\s+(?:should\s+be\s+issued|is\s+expected)",
        r"internal\s+(?:adjustment|memo|record)",
        r"reimbursement",
    ]
    administrative_doc_patterns = [
        r"purchase\s+request",
        r"budget\s+(?:projection|summary|forecast)",
        r"account\s+memo",
        r"expense\s+summary",
        r"approval\s+status",
        r"awaiting\s+(?:procurement|finance|manager)\s+approval",
        r"planning\s+worksheet",
    ]
    payment_patterns = [
        r"remit(?:tance)?",
        r"emittance",
        r"payment\s+terms",
        r"terms:\s*(?:net|pay|due)",
        r"due\s+on\s+receipt",
        r"pay\s+within\s+\d+\s+days",
        r"pay\s*within",
    ]
    payable_total_patterns = [
        r"amount\s+due",
        r"balance\s+to\s+pay",
        r"balance\s+due",
        r"final\s+payable",
        r"grand\s+total",
        r"total\s+due",
    ]
    counterparty_patterns = [
        r"bill\s+to",
        r"bill\s+t[ao]",
        r"client:",
        r"customer(?:\s+(?:ref|ret))?",
        r"prepared\s+for",
        r"for:",
        r"\bfor\s+[a-z]",
    ]
    charge_patterns = [
        r"service\s+charge",
        r"billing",
        r"fee\s+notice",
        r"monthly\s+service\s+charges",
        r"billing\s+summary",
    ]
    tax_patterns = [r"\bvat\b", r"sales\s+tax", r"\bgst\b", r"\btax\b"]

    if has_any(lowered, explicit_non_invoice_patterns):
        return False

    positive_score = 0
    negative_score = 0

    if has_any(lowered, administrative_doc_patterns):
        negative_score += 4
    if has_any(lowered, payment_patterns):
        positive_score += 3
    if has_any(lowered, payable_total_patterns):
        positive_score += 3
    if has_any(lowered, counterparty_patterns):
        positive_score += 2
    if has_any(lowered, charge_patterns):
        positive_score += 2
    if has_any(lowered, tax_patterns):
        positive_score += 1

    amount_rich_lines = sum(len(AMOUNT_RE.findall(line)) >= 1 for line in lines)
    if amount_rich_lines >= 3:
        positive_score += 1

    line_item_lines = sum(len(AMOUNT_RE.findall(line)) >= 2 for line in lines)
    if line_item_lines >= 2:
        positive_score += 1

    total_line_present = find_line_amount(lines, r"\b(?:grand\s+)?total\b") is not None
    if total_line_present:
        positive_score += 2

    title_line = lines[1] if len(lines) > 1 else (lines[0] if lines else "")
    if re.search(r"(request|projection|memo|expense|budget)", title_line, re.IGNORECASE):
        negative_score += 3

    has_payment_flow = has_any(lowered, payment_patterns)
    has_payable_total = has_any(lowered, payable_total_patterns)
    has_counterparty = has_any(lowered, counterparty_patterns)
    has_invoice_amount_context = has_payable_total or total_line_present

    return (
        has_payment_flow
        and has_invoice_amount_context
        and positive_score >= 4
        and positive_score > negative_score
    )

def extract_amounts(text: str) -> tuple[Decimal, Decimal]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    total_value = find_line_amount(lines, r"\btotal\b")
    amount_due_value = find_line_amount(lines, r"amount\s+due")
    if total_value is not None and amount_due_value is not None and total_value != amount_due_value:
        final_total = total_value
    else:
        final_total = None
        for pattern in [
            r"final\s+payable",
            r"balance\s+to\s+pay",
            r"amount\s+due",
            r"\btotal\b",
        ]:
            final_total = find_line_amount(lines, pattern)
            if final_total is not None:
                break

    if final_total is None:
        raise RuntimeError("Could not determine invoice total: " + text[:500])

    vat_value = None
    for pattern in [r"sales\s+tax", r"\bvat\b", r"\bgst\b", r"\btax\b"]:
        vat_value = find_line_amount(lines, pattern)
        if vat_value is not None:
            break

    return final_total, vat_value or Decimal("0.00")


rows: list[dict[str, str]] = []
total_sum = Decimal("0.00")
vat_sum = Decimal("0.00")

for path in sorted(p for p in DOCS_DIR.iterdir() if p.is_file()):
    text = extract_text(path)
    if is_invoice(text):
        total_amount, vat_amount = extract_amounts(text)
        destination = INVOICES_DIR / path.name
        rows.append(
            {
                "filename": path.name,
                "total_amount": format_amount(total_amount),
                "vat_amount": format_amount(vat_amount),
            }
        )
        total_sum += total_amount
        vat_sum += vat_amount
    else:
        destination = OTHER_DIR / path.name

    shutil.move(str(path), str(destination))

with SUMMARY_PATH.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["filename", "total_amount", "vat_amount"])
    writer.writeheader()
    writer.writerows(rows)
    writer.writerow(
        {
            "filename": "total",
            "total_amount": format_amount(total_sum),
            "vat_amount": format_amount(vat_sum),
        }
    )
PY
