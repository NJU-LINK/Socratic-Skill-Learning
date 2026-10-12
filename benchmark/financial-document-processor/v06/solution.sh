#!/bin/bash
set -euo pipefail

if ! command -v tesseract >/dev/null 2>&1 || ! command -v pdftotext >/dev/null 2>&1 || ! command -v pdftoppm >/dev/null 2>&1; then
  sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends poppler-utils tesseract-ocr
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD=(python3)
else
  PYTHON_CMD=(uv run --no-project python)
fi

"${PYTHON_CMD[@]}" - <<'PY'
from __future__ import annotations

import csv
from collections import deque
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

DOCS_DIR = Path('/app/documents')
INVOICES_DIR = Path('/app/invoices')
OTHER_DIR = Path('/app/other')
SUMMARY_PATH = INVOICES_DIR / 'summary.csv'

INVOICE_POSITIVE_PATTERNS = [
    r'\btax invoice\b',
    r'\bbilling document\b',
    r'\bclient billing\b',
    r'\binvoice no\b',
]

INVOICE_NEGATIVE_PATTERNS = [
    r'not a tax invoice',
    r'\bstatement of account\b',
    r'\bmonthly account statement\b',
    r'\bpro forma quote\b',
    r'\bpurchase order\b',
    r'\btravel expense summary\b',
]

AMOUNT_LINE_RE = re.compile(
    r'^(?P<label>[A-Za-z][A-Za-z /-]*?)\s+(?P<amount>-?[0-9][0-9,]*\.\d{2})\s*$'
)
AMOUNT_ONLY_RE = re.compile(r'^-?[0-9][0-9,]*\.\d{2}$')


def extract_pdf_text(path: Path) -> str:
    text_result = subprocess.run(
        ['pdftotext', '-layout', str(path), '-'],
        check=True,
        capture_output=True,
    )
    text = text_result.stdout.decode('utf-8', errors='ignore')
    if len(re.findall(r'[A-Za-z0-9]', text)) >= 20:
        return text

    with tempfile.TemporaryDirectory() as tmp_dir:
        prefix = str(Path(tmp_dir) / 'page')
        subprocess.run(
            ['pdftoppm', '-png', str(path), prefix],
            check=True,
            capture_output=True,
        )
        page_texts = []
        for image_path in sorted(Path(tmp_dir).glob('page-*.png')):
            result = subprocess.run(
                ['tesseract', str(image_path), 'stdout'],
                check=True,
                capture_output=True,
            )
            page_texts.append(result.stdout.decode('utf-8', errors='ignore'))
        return '\n'.join(page_texts)


def extract_text_with_tesseract(path: Path) -> str:
    result = subprocess.run(
        ['tesseract', str(path), 'stdout'],
        check=True,
        capture_output=True,
    )
    return result.stdout.decode('utf-8', errors='ignore')


def normalize(text: str) -> str:
    text = text.replace('\r', '\n')
    text = re.sub(r'[^\S\n]+', ' ', text)
    return '\n'.join(line.strip() for line in text.splitlines())


def is_invoice(text: str) -> bool:
    lowered = text.lower()
    if any(re.search(pattern, lowered) for pattern in INVOICE_NEGATIVE_PATTERNS):
        return False
    return any(re.search(pattern, lowered) for pattern in INVOICE_POSITIVE_PATTERNS)


def parse_decimal(value: str) -> Decimal:
    return Decimal(value.replace(',', ''))


def normalize_label(label: str) -> str:
    return ' '.join(label.lower().split())


def is_amount_label_candidate(label: str) -> bool:
    if 'invoice' in label and label != 'tax':
        return False
    if 'amount due' in label:
        return True
    if re.search(r'\b(vat|gst|tax|total)\b', label):
        return True
    return False


def find_amounts(text: str) -> tuple[Decimal, Decimal | None]:
    total_candidates: list[Decimal] = []
    amount_due_candidates: list[Decimal] = []
    vat_candidates: list[Decimal] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    extracted_pairs: list[tuple[str, Decimal]] = []
    pending_labels: deque[str] = deque()

    for line in lines:
        match = AMOUNT_LINE_RE.match(line)
        if match:
            label = normalize_label(match.group('label'))
            amount = parse_decimal(match.group('amount'))
            extracted_pairs.append((label, amount))
            continue

        if AMOUNT_ONLY_RE.match(line):
            if pending_labels:
                extracted_pairs.append((pending_labels.popleft(), parse_decimal(line)))
            continue

        label = normalize_label(line)
        if is_amount_label_candidate(label):
            pending_labels.append(label)

    for label, amount in extracted_pairs:
        if 'amount due' in label:
            amount_due_candidates.append(amount)
        if re.search(r'\b(vat|tax|gst)\b', label):
            vat_candidates.append(amount)
        if re.search(r'\btotal\b', label) and 'statement total' not in label and 'quoted total' not in label and 'order total' not in label and 'subtotal' not in label:
            total_candidates.append(amount)

    if not total_candidates and amount_due_candidates:
        total = amount_due_candidates[-1]
    elif total_candidates:
        total = total_candidates[-1]
    else:
        raise RuntimeError('Could not determine invoice total')

    vat = vat_candidates[-1] if vat_candidates else None
    return total, vat


def decimal_to_str(value: Decimal | None) -> str:
    if value is None:
        return ''
    quantized = value.quantize(Decimal('0.01'))
    return format(quantized, 'f')


def main() -> None:
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)
    OTHER_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[tuple[str, Decimal, Decimal | None]] = []

    for path in sorted(DOCS_DIR.iterdir()):
        if not path.is_file():
            continue

        text = extract_pdf_text(path) if path.suffix.lower() == '.pdf' else extract_text_with_tesseract(path)
        text = normalize(text)

        if is_invoice(text):
            total, vat = find_amounts(text)
            destination = INVOICES_DIR / path.name
            rows.append((path.name, total, vat))
        else:
            destination = OTHER_DIR / path.name

        shutil.move(str(path), destination)

    rows.sort(key=lambda row: row[0])
    total_amount_sum = sum((row[1] for row in rows), start=Decimal('0.00'))
    vat_amount_sum = sum((row[2] or Decimal('0.00') for row in rows), start=Decimal('0.00'))

    with SUMMARY_PATH.open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['filename', 'total_amount', 'vat_amount'])
        for filename, total, vat in rows:
            writer.writerow([filename, decimal_to_str(total), decimal_to_str(vat) if vat is not None else '0'])
        writer.writerow(['total', decimal_to_str(total_amount_sum), decimal_to_str(vat_amount_sum)])


if __name__ == '__main__':
    main()
PY
