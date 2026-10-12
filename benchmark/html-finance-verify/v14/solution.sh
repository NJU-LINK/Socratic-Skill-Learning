#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from html.parser import HTMLParser
from pathlib import Path


LOCAL_DIR = Path.cwd()
APP_DIR = Path('/app')
REPORT_PATH = (LOCAL_DIR / 'cash-flow-report.html') if (LOCAL_DIR / 'cash-flow-report.html').exists() else (APP_DIR / 'cash-flow-report.html')
OUTPUT_PATH = (LOCAL_DIR / 'value.txt') if LOCAL_DIR.exists() else (APP_DIR / 'value.txt')


def parse_amount(text: str) -> int:
    cleaned = text.strip().replace('$', '').replace(',', '')
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    return int(cleaned)


class CashFlowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tbody = False
        self.in_row = False
        self.in_cell = False
        self.current_tag = None
        self.current_row_class = set()
        self.current_cells = []
        self.current_cell_parts = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'tbody':
            self.in_tbody = True
        elif self.in_tbody and tag == 'tr':
            self.in_row = True
            self.current_row_class = set(attrs_dict.get('class', '').split())
            self.current_cells = []
        elif self.in_row and tag in {'td', 'th'}:
            self.in_cell = True
            self.current_tag = tag
            self.current_cell_parts = []

    def handle_endtag(self, tag):
        if tag == 'tbody':
            self.in_tbody = False
        elif self.in_row and tag in {'td', 'th'} and self.in_cell:
            text = ''.join(self.current_cell_parts).strip()
            self.current_cells.append(text)
            self.in_cell = False
            self.current_tag = None
        elif self.in_row and tag == 'tr':
            if 'section' in self.current_row_class:
                section_name = self.current_cells[0] if self.current_cells else ''
                self.rows.append({'type': 'section', 'section': section_name})
            elif len(self.current_cells) >= 3:
                line, description, amount = self.current_cells[:3]
                self.rows.append(
                    {
                        'type': 'value',
                        'line': line,
                        'description': description,
                        'amount': parse_amount(amount),
                        'is_total': 'total' in self.current_row_class,
                    }
                )
            self.in_row = False
            self.current_row_class = set()
            self.current_cells = []

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell_parts.append(data)


def load_rows(path: Path):
    parser = CashFlowParser()
    parser.feed(path.read_text(encoding='utf-8'))
    return parser.rows


def find_incorrect_metric(rows):
    operating = []
    investing = []
    financing = []
    op_total = inv_total = fin_total = net_change = beginning_cash = ending_cash = None
    current_section = None

    for row in rows:
        if row['type'] == 'section':
            current_section = row['section']
            continue

        if current_section == 'Cash flows from operating activities':
            if row['is_total']:
                op_total = row
            else:
                operating.append(row)
        elif current_section == 'Cash flows from investing activities':
            if row['is_total']:
                inv_total = row
            else:
                investing.append(row)
        elif current_section == 'Cash flows from financing activities':
            if row['is_total']:
                fin_total = row
            else:
                financing.append(row)
        elif current_section == 'Reconciliation of cash':
            if row['description'] == 'Net increase in cash and cash equivalents':
                net_change = row
            elif row['description'] == 'Cash and cash equivalents at beginning of year':
                beginning_cash = row
            elif row['description'] == 'Cash and cash equivalents at end of year':
                ending_cash = row

    numeric_rows = operating + investing + financing + [op_total, inv_total, fin_total, net_change, beginning_cash, ending_cash]
    amounts = {row['line']: row['amount'] for row in numeric_rows}
    row_by_line = {row['line']: row for row in numeric_rows}

    equations = [
        {op_total['line']: 1, **{row['line']: -1 for row in operating}},
        {inv_total['line']: 1, **{row['line']: -1 for row in investing}},
        {fin_total['line']: 1, **{row['line']: -1 for row in financing}},
        {net_change['line']: 1, op_total['line']: -1, inv_total['line']: -1, fin_total['line']: -1},
        {ending_cash['line']: 1, beginning_cash['line']: -1, net_change['line']: -1},
    ]

    candidate_lines = {op_total['line'], inv_total['line'], fin_total['line'], net_change['line']}
    candidates = []
    for line, observed in amounts.items():
        if line not in candidate_lines:
            continue

        implied_values = []
        valid = True

        for equation in equations:
            residual = sum(coeff * amounts[var_line] for var_line, coeff in equation.items())
            coeff = equation.get(line)

            if coeff is None:
                if residual != 0:
                    valid = False
                    break
                continue

            implied = observed - (residual / coeff)
            if implied != int(implied):
                valid = False
                break
            implied_values.append(int(implied))

        if not valid:
            continue

        corrected_values = {value for value in implied_values}
        if len(corrected_values) != 1:
            continue

        corrected = corrected_values.pop()
        if corrected == observed:
            continue

        candidates.append((line, observed))

    if len(candidates) != 1:
        raise SystemExit(f'Expected exactly one incorrect metric, found {len(candidates)} candidates')

    return candidates[0]


line, amount = find_incorrect_metric(load_rows(REPORT_PATH))
OUTPUT_PATH.write_text(f'{line},{amount}', encoding='utf-8')
PY
