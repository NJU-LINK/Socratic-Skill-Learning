#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from decimal import Decimal, ROUND_HALF_UP
from html.parser import HTMLParser
from pathlib import Path


class EarningsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current_section = None
        self.in_h2 = False
        self.h2_parts = []
        self.in_row = False
        self.current_row = None
        self.in_cell = False
        self.current_cell_parts = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == 'h2':
            self.in_h2 = True
            self.h2_parts = []
            return

        if tag == 'tr':
            self.in_row = True
            self.current_row = {
                'line_no': self.getpos()[0],
                'section': self.current_section,
                'cells': [],
            }
            return

        if self.in_row and tag in {'td', 'th'}:
            self.in_cell = True
            self.current_cell_parts = []

    def handle_endtag(self, tag):
        if tag == 'h2' and self.in_h2:
            self.current_section = ' '.join(''.join(self.h2_parts).split())
            self.in_h2 = False
            self.h2_parts = []
            return

        if self.in_row and tag in {'td', 'th'} and self.in_cell:
            cell_text = ' '.join(''.join(self.current_cell_parts).split())
            self.current_row['cells'].append(cell_text)
            self.in_cell = False
            self.current_cell_parts = []
            return

        if tag == 'tr' and self.in_row:
            if len(self.current_row['cells']) >= 2:
                self.rows.append({
                    'line_no': self.current_row['line_no'],
                    'section': self.current_row['section'],
                    'label': self.current_row['cells'][0],
                    'value': self.current_row['cells'][1],
                })
            self.in_row = False
            self.current_row = None

    def handle_data(self, data):
        if self.in_h2:
            self.h2_parts.append(data)
        if self.in_cell:
            self.current_cell_parts.append(data)


html_path = Path('/app/aurora_q2_earnings_release.html')
output_path = Path('/app/value.txt')

parser = EarningsParser()
parser.feed(html_path.read_text())
rows = parser.rows


def get_row(label: str, section_name: str | None = None):
    matches = [
        row for row in rows
        if row['label'] == label and (section_name is None or row['section'] == section_name)
    ]
    if len(matches) != 1:
        raise SystemExit(f'Expected exactly one row for {label!r} in {section_name!r}, found {len(matches)}')
    return matches[0]


def parse_decimal(value: str) -> Decimal:
    return Decimal(value.replace(',', ''))


def decimal_places(value: str) -> int:
    return len(value.split('.', 1)[1]) if '.' in value else 0


def round_like(value: Decimal, template: str) -> Decimal:
    places = decimal_places(template)
    quantum = Decimal('1').scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


summary_section = 'Quarter Highlights'
note_section = 'Note 4. Earnings Per Share Reconciliation'

net_income = parse_decimal(get_row('Net income attributable to common shareholders', note_section)['value'])
basic_shares_row = get_row('Weighted-average common shares outstanding, basic', note_section)
effect_row = get_row('Effect of dilutive stock awards', note_section)
diluted_shares_row = get_row('Weighted-average common shares outstanding, diluted', note_section)
diluted_eps_row = get_row('Diluted earnings per share', summary_section)

basic_shares = parse_decimal(basic_shares_row['value'])
effect = parse_decimal(effect_row['value'])
diluted_shares = parse_decimal(diluted_shares_row['value'])
diluted_eps = parse_decimal(diluted_eps_row['value'])

expected_diluted_shares = basic_shares + effect
expected_diluted_eps_from_reported_shares = round_like(net_income / diluted_shares, diluted_eps_row['value'])
expected_diluted_eps_from_reconciled_shares = round_like(net_income / expected_diluted_shares, diluted_eps_row['value'])

if diluted_shares != expected_diluted_shares and diluted_eps == expected_diluted_eps_from_reconciled_shares:
    answer_row = diluted_shares_row
elif diluted_eps != expected_diluted_eps_from_reported_shares and diluted_shares == expected_diluted_shares:
    answer_row = diluted_eps_row
else:
    raise SystemExit('Unable to isolate a single incorrect diluted metric')

output_path.write_text(f"{answer_row['line_no']},{answer_row['value']}\n")
PY
