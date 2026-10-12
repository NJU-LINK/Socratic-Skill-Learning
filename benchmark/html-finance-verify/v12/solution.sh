#!/bin/bash
set -euo pipefail

export REPORT_PATH="${REPORT_PATH:-/app/report.html}"
export OUTPUT_PATH="${OUTPUT_PATH:-/app/value.txt}"

python3 - <<'PY'
import os
from html.parser import HTMLParser
from pathlib import Path


REPORT_PATH = Path(os.environ['REPORT_PATH'])
OUTPUT_PATH = Path(os.environ['OUTPUT_PATH'])


def parse_amount(text: str) -> float:
    text = text.strip()
    negative = False
    if '(' in text and ')' in text:
        negative = True
    cleaned = text.replace('$', '').replace(',', '').replace('million', '').replace('shares', '')
    cleaned = cleaned.replace('outstanding', '').replace('per', '').replace('net income', '')
    cleaned = cleaned.replace('common stockholders', '').strip()
    cleaned = cleaned.replace('(', '').replace(')', '').strip()
    value = float(cleaned)
    return -value if negative else value


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tr = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.in_tr = True
            self.current_row = []
        elif self.in_tr and tag in {'td', 'th'}:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if self.in_tr and tag in {'td', 'th'} and self.in_cell:
            cell = ' '.join(' '.join(self.current_cell).split())
            self.current_row.append(cell)
            self.in_cell = False
            self.current_cell = []
        elif tag == 'tr' and self.in_tr:
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_tr = False
            self.current_row = []


parser = TableParser()
parser.feed(REPORT_PATH.read_text())

net_income = None
basic_shares = None
diluted_shares = None
basic_eps = None
diluted_eps = None
basic_line = None
diluted_line = None

for row in parser.rows:
    if len(row) != 3:
        continue
    line, description, amount = row
    description_lower = description.lower()
    if description_lower == 'net income available to common stockholders' and net_income is None:
        net_income = parse_amount(amount)
    elif description_lower == 'basic net income per share':
        basic_eps = parse_amount(amount)
        basic_line = int(line)
    elif description_lower == 'diluted net income per share':
        diluted_eps = parse_amount(amount)
        diluted_line = int(line)
    elif description_lower == 'basic weighted average shares outstanding' and basic_shares is None:
        basic_shares = parse_amount(amount)
    elif description_lower == 'diluted weighted average shares outstanding' and diluted_shares is None:
        diluted_shares = parse_amount(amount)

if None in {net_income, basic_shares, diluted_shares, basic_eps, diluted_eps, basic_line, diluted_line}:
    raise SystemExit('Failed to parse required values from report')

expected_basic = round(net_income / basic_shares + 1e-12, 2)
expected_diluted = round(net_income / diluted_shares + 1e-12, 2)

if abs(basic_eps - expected_basic) > 0.005:
    wrong_line = basic_line
    wrong_value = basic_eps
elif abs(diluted_eps - expected_diluted) > 0.005:
    wrong_line = diluted_line
    wrong_value = diluted_eps
else:
    raise SystemExit('No inconsistent EPS metric found')

OUTPUT_PATH.write_text(f'{wrong_line},{wrong_value:.2f}')
PY
