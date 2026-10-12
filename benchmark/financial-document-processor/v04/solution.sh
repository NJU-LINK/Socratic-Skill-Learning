#!/bin/bash
set -euo pipefail

sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources

export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
apt-get install -y --no-install-recommends tesseract-ocr poppler-utils python3-pil >/dev/null

python3 - <<'PY'
import csv
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps


DOCS_DIR = Path(os.environ.get('DOCS_DIR_OVERRIDE', '/app/documents'))
INVOICES_DIR = Path(os.environ.get('INVOICES_DIR_OVERRIDE', '/app/invoices'))
OTHER_DIR = Path(os.environ.get('OTHER_DIR_OVERRIDE', '/app/other'))
SUMMARY_PATH = INVOICES_DIR / 'summary.csv'

AMOUNT_TOKEN_RE = re.compile(r'[A-Za-z0-9.,]+')
ZERO = Decimal('0.00')
INVOICE_MARKERS = [
    'invoice',
    'tax invoice',
    'bill to',
    'invoice no',
    'invoice number',
    'payment terms',
    'remit to',
    'remittance address',
    'amount due',
    'grand total',
]
NON_INVOICE_MARKERS = [
    'not an invoice',
    'internal',
    'reimbursement',
    'expense report',
    'expense claim',
    'expense rollup',
    'purchase summary',
    'budget statement',
    'rebate statement',
    'claim sheet',
    'spend report',
    'procurement review',
    'payment review',
    'not a bill for payment',
    'no remittance requested',
    'planning purposes only',
]


def load_pages(path: Path):
    pages = []
    if path.suffix.lower() == '.pdf':
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = str(Path(tmpdir) / 'page')
            subprocess.run(
                ['pdftoppm', '-r', '400', '-png', str(path), prefix],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for page_path in sorted(Path(tmpdir).glob('page-*.png')):
                with Image.open(page_path) as image:
                    pages.append(image.convert('L').copy())
    else:
        with Image.open(path) as image:
            pages.append(image.convert('L').copy())
    return pages


def preprocess_page(image: Image.Image, scale: int, threshold: int) -> Image.Image:
    processed = ImageOps.autocontrast(image)
    processed = processed.resize((processed.width * scale, processed.height * scale))
    processed = processed.filter(ImageFilter.SHARPEN)
    return processed.point(lambda value: 255 if value > threshold else 0)


def ocr_image(image: Image.Image, psm: str) -> str:
    with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
        image.save(tmp.name)
        result = subprocess.run(
            ['tesseract', tmp.name, 'stdout', '--psm', psm, '-c', 'preserve_interword_spaces=1'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return result.stdout


def extract_text_variants(path: Path) -> list[str]:
    pages = load_pages(path)
    variants = []
    configs = [
        ('raw', '6', None),
        ('raw', '4', None),
        ('prep160', '6', (3, 160)),
        ('prep170', '6', (3, 170)),
        ('prep180', '6', (3, 180)),
    ]

    for _name, psm, preprocess in configs:
        page_texts = []
        for page in pages:
            image = preprocess_page(page, *preprocess) if preprocess else page
            page_texts.append(ocr_image(image, psm))
        combined = '\n'.join(page_texts)
        if combined not in variants:
            variants.append(combined)
    return variants


def normalize(text: str) -> str:
    lowered = text.lower().replace('|', 'i')
    lowered = lowered.replace('bill ta', 'bill to')
    lowered = lowered.replace('emit to', 'remit to')
    lowered = lowered.replace('invoice not', 'invoice no')
    lowered = lowered.replace('invoice nar', 'invoice no')
    lowered = re.sub(r'\btoa\b', 'total', lowered)
    lowered = re.sub(r'\bvar\b', 'vat', lowered)
    lowered = re.sub(r'\bast\b', 'gst', lowered)
    lowered = lowered.replace('grand total...', 'grand total ')
    lowered = re.sub(r'\s+', ' ', lowered)
    lowered = lowered.replace('grand tetal', 'grand total')
    lowered = lowered.replace('tetal', 'total')
    lowered = lowered.replace('arnount', 'amount')
    lowered = lowered.replace('takinvoice', 'tax invoice')
    return lowered


def normalize_line(line: str) -> str:
    return normalize(line)


def line_has_label(line: str, label_kind: str) -> bool:
    if label_kind == 'subtotal':
        return 'subtotal' in line
    if label_kind == 'amount_due':
        return 'amount due' in line
    if label_kind == 'grand_total':
        return 'grand total' in line
    if label_kind == 'total':
        return re.search(r'(?<!sub)(?<!grand )\btotal\b', line) is not None
    if label_kind == 'tax':
        return any(word in line for word in ['vat', 'tax', 'gst']) and 'invoice' not in line
    return False


def is_invoice(text: str) -> bool:
    score = sum(marker in text for marker in INVOICE_MARKERS)
    penalties = sum(marker in text for marker in NON_INVOICE_MARKERS)
    if 'invoice' in text and 'not an invoice' not in text:
        score += 2
    return score >= 4 and penalties == 0


def parse_amount_from_token(token: str):
    cleaned = re.sub(r'[^\d,\.]', '', token)
    if not re.search(r'\d', cleaned):
        return None

    digits_only = re.sub(r'\D', '', cleaned)
    if len(digits_only) < 3:
        return None

    separators = [index for index, char in enumerate(cleaned) if char in ',.']
    if separators:
        last_sep = separators[-1]
        left = re.sub(r'\D', '', cleaned[:last_sep])
        right = re.sub(r'\D', '', cleaned[last_sep + 1 :])
        if left and len(right) == 2:
            return Decimal(f'{int(left)}.{right}')

    return Decimal(f'{int(digits_only[:-2])}.{digits_only[-2:]}')


def parse_amount_from_line(line: str):
    tokens = [token for token in AMOUNT_TOKEN_RE.findall(line) if re.search(r'\d', token)]
    for token in reversed(tokens):
        amount = parse_amount_from_token(token)
        if amount is not None:
            return amount
    return None


def collect_candidates(texts, label_kind: str) -> Counter:
    amounts = Counter()
    for text in texts:
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            line = normalize_line(stripped)
            if not line_has_label(line, label_kind):
                continue
            amount = parse_amount_from_line(line)
            if amount is not None:
                amounts[amount] += 1
    return amounts


def choose_invoice_amounts(subtotals: Counter, totals: Counter, dues: Counter, taxes: Counter):
    subtotal_values = list(subtotals) or [None]
    total_sources = []
    for total in totals:
        total_sources.append((total, 0, totals[total]))
    for total in dues:
        total_sources.append((total, 1, dues[total]))
    if subtotals and taxes:
        for subtotal in subtotals:
            for tax in taxes:
                total_sources.append(((subtotal + tax).quantize(Decimal('0.01')), 2, subtotals[subtotal] + taxes[tax]))

    best = None

    for total, source_penalty, total_support in total_sources:
        for subtotal in subtotal_values:
            if subtotal is not None and total < subtotal:
                continue

            matching_taxes = []
            for tax, tax_support in taxes.items():
                if subtotal is None:
                    continue
                diff = abs((subtotal + tax) - total)
                if diff <= Decimal('0.02'):
                    matching_taxes.append((tax, tax_support, diff))

            if matching_taxes:
                for tax, tax_support, diff in matching_taxes:
                    support = total_support + tax_support + (subtotals[subtotal] if subtotal is not None else 0)
                    score = (diff, -support, source_penalty, total)
                    candidate = (score, total.quantize(Decimal('0.01')), tax.quantize(Decimal('0.01')))
                    if best is None or candidate < best:
                        best = candidate
                continue

            if subtotal is None and taxes:
                for tax, tax_support in taxes.items():
                    if ZERO <= tax <= total:
                        support = total_support + tax_support
                        score = (Decimal('0.02'), -support, source_penalty, total)
                        candidate = (score, total.quantize(Decimal('0.01')), tax.quantize(Decimal('0.01')))
                        if best is None or candidate < best:
                            best = candidate
                continue

            if subtotal is not None:
                derived_tax = (total - subtotal).quantize(Decimal('0.01'))
                if ZERO <= derived_tax <= total:
                    support = total_support + subtotals[subtotal] + taxes.get(derived_tax, 0)
                    score = (Decimal('0.03'), -support, source_penalty, total)
                    candidate = (score, total.quantize(Decimal('0.01')), derived_tax)
                    if best is None or candidate < best:
                        best = candidate

    if best is not None:
        return best[1], best[2]

    if totals:
        total = min(totals, key=lambda value: (-totals[value], value))
        return total.quantize(Decimal('0.01')), ZERO
    if dues:
        total = min(dues, key=lambda value: (-dues[value], value))
        return total.quantize(Decimal('0.01')), ZERO
    return ZERO, ZERO


def format_amount(value: Decimal) -> str:
    quantized = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f'{quantized:.2f}'


INVOICES_DIR.mkdir(parents=True, exist_ok=True)
OTHER_DIR.mkdir(parents=True, exist_ok=True)

rows = []
total_amount_sum = Decimal('0')
vat_amount_sum = Decimal('0')

for path in sorted(DOCS_DIR.iterdir()):
    if not path.is_file():
        continue

    text_variants = extract_text_variants(path)
    normalized_text = normalize(' '.join(text_variants))
    destination = OTHER_DIR

    if is_invoice(normalized_text):
        destination = INVOICES_DIR
        subtotals = collect_candidates(text_variants, 'subtotal')
        totals = collect_candidates(text_variants, 'grand_total') + collect_candidates(text_variants, 'total')
        dues = collect_candidates(text_variants, 'amount_due')
        taxes = collect_candidates(text_variants, 'tax')

        total_amount, vat_amount = choose_invoice_amounts(subtotals, totals, dues, taxes)

        rows.append(
            {
                'filename': path.name,
                'total_amount': format_amount(total_amount),
                'vat_amount': format_amount(vat_amount),
            }
        )
        total_amount_sum += total_amount
        vat_amount_sum += vat_amount

    shutil.move(str(path), destination / path.name)

with SUMMARY_PATH.open('w', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=['filename', 'total_amount', 'vat_amount'])
    writer.writeheader()
    writer.writerows(rows)
    writer.writerow(
        {
            'filename': 'total',
            'total_amount': format_amount(total_amount_sum),
            'vat_amount': format_amount(vat_amount_sum),
        }
    )
PY
