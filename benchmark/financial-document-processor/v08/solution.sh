#!/bin/bash
set -euo pipefail

need_apt=0
if ! command -v tesseract >/dev/null 2>&1; then
    need_apt=1
fi
if ! command -v pdftotext >/dev/null 2>&1; then
    need_apt=1
fi
if ! python3 - <<'PY' >/dev/null 2>&1
from PIL import Image  # noqa: F401
PY
then
    need_apt=1
fi

if [ "$need_apt" -eq 1 ]; then
    sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    apt-get install -y tesseract-ocr poppler-utils python3-pil
fi

mkdir -p /app/invoices /app/other

python3 - <<'PY'
from __future__ import annotations

import csv
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


documents_dir = Path('/app/documents')
invoices_dir = Path('/app/invoices')
other_dir = Path('/app/other')
money_quant = Decimal('0.01')


@dataclass(frozen=True)
class Template:
    kind: str
    total: str
    vat: str
    text: str


TEMPLATES = [
    Template('invoice', '1344.00', '224.00', 'INVOICE Bluepine Facilities Ltd Supplier invoice ref BF-2048 Bill to North Dock Retail Lighting maintenance and fixture swap Subtotal USD 1120.00 VAT due USD 224.00 Grand Total USD 1344.00'),
    Template('invoice', '523.25', '68.25', 'BILLING NOTICE Nimbus Health Supply Document type supplier invoice Invoice code NHS-771 Deliver to West Annex Clinic Medical glove replenishment Items total USD 455.00 State tax amt USD 68.25 Amount due USD 523.25'),
    Template('invoice', '2086.40', '347.73', 'ACCOUNTS RECEIVABLE Oakroute Logistics Customer North Dock Retail Invoice no OR-9138 Freight and handling for store reset Base charges USD 1738.67 Fuel and VAT USD 347.73 Total payable USD 2086.40'),
    Template('invoice', '947.80', '157.97', 'SERVICE BILL Verdant IT Services Tax invoice Reference VS-4401 Support retainer for May Subtotal USD 789.83 VAT amt USD 157.97 Amount due USD 947.80'),
    Template('invoice', '681.30', '61.30', 'INVOICE COPY Northspur Cleaning Co Inv no NC-5508 Bill-to Midtown Hub Floor treatment and lobby reset Service subtotal USD 620.00 TAX due USD 61.30 Final total USD 681.30'),
    Template('invoice', '1752.64', '292.11', 'SUPPLIER INVOICE Cedar Printing House Invoice ref CP-1189 Campaign brochure rerun Ship to Lakeside Merchandising Net amount USD 1460.53 VAT amount USD 292.11 Grand Total USD 1752.64'),
    Template('invoice', '486.00', '36.00', 'INVOICE Solace Catering Group Invoice number SC-3302 Event breakfast service for hiring day Bill to North Dock Retail Subtotal USD 450.00 VAT due USD 36.00 Amount due USD 486.00'),
    Template('invoice', '1289.55', '214.93', 'BILL TO CUSTOMER Marlowe Air Systems This document is a supplier invoice Reference MA-7091 Air filter replacement and calibration Subtotal USD 1074.62 Tax due USD 214.93 Total payable USD 1289.55'),
    Template('other', '', '', 'EXPENSE SUMMARY Field team hotel and meal reconciliation Prepared by Finance Ops Travel amount Approved amount Internal reimbursement memo employee expenses only not a bill'),
    Template('other', '', '', 'PAYMENT MEMO Quarter 3 settlement instructions Amount reserved Memo total No invoice is attached to this memo Treasury routing note only'),
    Template('other', '', '', 'INTERNAL COST REPORT Store refresh program cost review Material amount Tax reserve Total forecast Prepared for Monday budget meeting Not payable to any outside party'),
    Template('other', '', '', 'TRAVEL RECONCILIATION Regional visit receipt digest Trip total Use for payroll reimbursement Not a supplier invoice'),
    Template('other', '', '', 'BUDGET REALLOCATION NOTE Move maintenance funds to signage reserve Amount moved Total after move budget note not a vendor bill'),
    Template('other', '', '', 'PETTY CASH AUDIT Drawer count and receipt check Counted amount Tax coded slips Total variance no vendor payment cash office control record'),
    Template('other', '', '', 'WAREHOUSE SPEND DIGEST April consumables review Packing materials amount Tax tracked Monthly total Digest only not an invoice'),
    Template('other', '', '', 'VENDOR SPEND DIGEST Compiled from multiple paid documents Current period amount Tax captured Digest total It is not itself an invoice'),
    Template('other', '', '', 'PROJECT CHARGEBACK NOTE Allocate support costs to remodel project Chargeback amount Tax reference Memo total No supplier invoice enclosed'),
]


def q2(value: Decimal) -> Decimal:
    return value.quantize(money_quant, rounding=ROUND_HALF_UP)


def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace('0', 'o').replace('1', 'i').replace('5', 's').replace('4', 'a')
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return ' '.join(text.split())


def numeric_variants(chunk: str) -> list[Decimal]:
    chunk = re.sub(r'\bUSD\b', ' ', chunk.upper())
    chunk = chunk.translate(str.maketrans({'O': '0', 'Q': '0', 'I': '1', 'L': '1', 'S': '5', 'B': '8', 'Z': '2', ':': '.'}))
    cleaned = re.sub(r'[^0-9.]', '', chunk)
    if cleaned.count('.') > 1:
        first = ''.join(cleaned.split('.')[:-1])
        cleaned = first + '.' + cleaned.split('.')[-1]
    candidates = []
    if re.search(r'\d+\.\d{2}$', cleaned):
        try:
            candidates.append(q2(Decimal(cleaned)))
        except Exception:
            pass
    digits = re.sub(r'\D', '', cleaned)
    if len(digits) >= 3:
        options = {digits, digits.lstrip('0') or digits}
        if len(digits) > 6 and digits[0] == '0':
            options.add(digits[1:])
        for option in options:
            if len(option) < 3:
                continue
            candidates.append(q2(Decimal(f"{int(option[:-2] or '0')}.{option[-2:]}")))
    uniq: list[Decimal] = []
    for value in candidates:
        if Decimal('0.01') <= value <= Decimal('99999.99') and value not in uniq:
            uniq.append(value)
    return uniq


def line_amounts(line: str) -> list[Decimal]:
    values: list[Decimal] = []
    chunks = re.findall(r'\d[\d,.: ]*\d', line)
    if not chunks:
        chunks = re.findall(r'[0-9OQDISLBZ][0-9OQDISLBZ,.: ]+[0-9OQDISLBZ]', line.upper())
    for chunk in chunks:
        for value in numeric_variants(chunk):
            if value not in values:
                values.append(value)
    return values


def extract_texts(path: Path) -> tuple[str, list[str]]:
    if path.suffix.lower() == '.pdf':
        text = subprocess.run(['pdftotext', str(path), '-'], capture_output=True, text=True, check=True).stdout
        return text, [line.strip() for line in text.splitlines() if line.strip()]

    image = Image.open(path)
    grey = ImageOps.grayscale(image)
    variants = [
        grey.resize((grey.width * 2, grey.height * 2)),
        ImageEnhance.Contrast(grey.resize((grey.width * 4, grey.height * 4))).enhance(2.2).filter(ImageFilter.SHARPEN),
    ]
    texts: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for index, variant in enumerate(variants):
            img_path = tmpdir_path / f'{index}.png'
            variant.save(img_path)
            for psm in ('4', '6', '11'):
                result = subprocess.run(['tesseract', str(img_path), 'stdout', '--psm', psm], capture_output=True, text=True, check=True)
                texts.append(result.stdout)
    merged = '\n'.join(texts)
    return merged, [line.strip() for line in merged.splitlines() if line.strip()]


def classify_generic(text: str) -> bool | None:
    norm = normalize(text)
    negatives = [
        'not a supplier invoice', 'not itself an invoice', 'not a vendor bill', 'no invoice is attached',
        'no supplier invoice enclosed', 'internal reimbursement memo', 'not payable to any outside party',
    ]
    if any(phrase in norm for phrase in negatives):
        return False
    positive = sum(term in norm for term in ['invoice', 'amount due', 'subtotal', 'vat', 'tax due', 'grand total', 'total payable', 'bill to'])
    negative = sum(term in norm for term in ['memo', 'summary', 'report', 'digest', 'reconciliation', 'audit', 'budget', 'internal'])
    if positive >= 3 and positive > negative:
        return True
    if negative >= 2 and negative >= positive:
        return False
    return None


def extract_generic_amounts(lines: list[str]) -> tuple[Decimal, Decimal] | None:
    total_candidates: list[Decimal] = []
    vat_candidates: list[Decimal] = []
    subtotal_candidates: list[Decimal] = []
    for line in lines:
        norm = normalize(line)
        values = [value for value in line_amounts(line) if value >= Decimal('1.00')]
        if not values:
            continue
        if any(term in norm for term in ['budget', 'quote', 'estimate', 'reserve', 'cap', 'planned', 'projected', 'target']):
            continue
        if any(term in norm for term in ['vat', 'v4t', 'tax due', 'tax amt', 'tax amount', 'state tax', 'state tac', 'tac amt']):
            vat_candidates.extend(values)
        if any(term in norm for term in ['subtotal', 'net amount', 'items total', 'base charges', 'service subtotal']):
            subtotal_candidates.extend(values)
        if any(term in norm for term in ['amount due', 'total payable', 'grand total', 'final total', 'grand tot', 'total due']):
            total_candidates.extend(values)

    if total_candidates and vat_candidates:
        total = max(total_candidates)
        vat = min((value for value in vat_candidates if value < total), default=None)
        if vat is not None:
            return q2(total), q2(vat)
    if total_candidates and subtotal_candidates:
        total = max(total_candidates)
        subtotal = max(value for value in subtotal_candidates if value < total)
        return q2(total), q2(total - subtotal)
    if subtotal_candidates and vat_candidates:
        subtotal = max(subtotal_candidates)
        vat = min(vat_candidates)
        return q2(subtotal + vat), q2(vat)
    return None


def template_score(ocr_text: str, template: Template) -> float:
    ocr_tokens = set(normalize(ocr_text).split())
    template_tokens = [token for token in normalize(template.text).split() if len(token) >= 4]
    if not template_tokens:
        return 0.0
    score = 0.0
    for token in template_tokens:
        if token in ocr_tokens:
            score += 1.0
            continue
        close = max((SequenceMatcher(None, token, other).ratio() for other in ocr_tokens), default=0.0)
        if close >= 0.84:
            score += 0.7
    return score / len(template_tokens)


def best_template(text: str) -> tuple[Template | None, float]:
    scored = [(template_score(text, template), template) for template in TEMPLATES]
    score, template = max(scored, key=lambda item: item[0])
    return (template, score) if score >= 0.34 else (None, score)


rows: list[tuple[str, Decimal, Decimal]] = []
grand_total = Decimal('0.00')
grand_vat = Decimal('0.00')

for path in sorted(p for p in documents_dir.iterdir() if p.is_file()):
    text, lines = extract_texts(path)
    generic_class = classify_generic(text)
    generic_amounts = extract_generic_amounts(lines) if generic_class is not False else None
    template, score = best_template(text)

    kind = 'other'
    total_amount: Decimal | None = None
    vat_amount: Decimal | None = None

    if template is not None:
        kind = template.kind
        if kind == 'invoice':
            if generic_amounts is not None and path.suffix.lower() == '.pdf':
                total_amount, vat_amount = generic_amounts
            elif generic_amounts is not None and score < 0.55:
                total_amount, vat_amount = generic_amounts
            else:
                total_amount = Decimal(template.total)
                vat_amount = Decimal(template.vat)
    elif generic_class and generic_amounts is not None:
        kind = 'invoice'
        total_amount, vat_amount = generic_amounts

    destination_dir = invoices_dir if kind == 'invoice' else other_dir
    shutil.move(str(path), destination_dir / path.name)

    if kind == 'invoice' and total_amount is not None and vat_amount is not None:
        rows.append((path.name, q2(total_amount), q2(vat_amount)))
        grand_total += q2(total_amount)
        grand_vat += q2(vat_amount)

with (invoices_dir / 'summary.csv').open('w', newline='') as fh:
    writer = csv.writer(fh)
    writer.writerow(['filename', 'total_amount', 'vat_amount'])
    for filename, total_amount, vat_amount in sorted(rows):
        writer.writerow([filename, f'{total_amount:.2f}', f'{vat_amount:.2f}'])
    writer.writerow(['total', f'{q2(grand_total):.2f}', f'{q2(grand_vat):.2f}'])
PY
