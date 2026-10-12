#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from html.parser import HTMLParser
import os
from pathlib import Path


def resolve_input_path() -> Path:
    env_path = os.environ.get('REPORT_PATH')
    if env_path:
        return Path(env_path)

    default = Path('/app/q2_earnings_report.html')
    if default.exists():
        return default

    local = Path.cwd() / 'app' / 'q2_earnings_report.html'
    if local.exists():
        return local

    raise FileNotFoundError('Could not locate q2_earnings_report.html')


def resolve_output_path() -> Path:
    env_path = os.environ.get('OUTPUT_PATH')
    if env_path:
        return Path(env_path)

    return INPUT_PATH.parent / 'value.txt'


INPUT_PATH = resolve_input_path()
OUTPUT_PATH = resolve_output_path()


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cells = []
        self.current_text = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == 'tbody':
            self.in_tbody = True
        elif tag == 'tr' and self.in_tbody:
            self.in_tr = True
            self.current_cells = []
        elif tag == 'td' and self.in_tr:
            self.in_td = True
            self.current_text = []

    def handle_endtag(self, tag):
        if tag == 'td' and self.in_td:
            self.current_cells.append(''.join(self.current_text).strip())
            self.in_td = False
        elif tag == 'tr' and self.in_tr:
            if len(self.current_cells) == 3:
                self.rows.append(tuple(self.current_cells))
            self.in_tr = False
        elif tag == 'tbody':
            self.in_tbody = False

    def handle_data(self, data):
        if self.in_td:
            self.current_text.append(data)


def parse_money(value: str) -> float:
    return float(value.replace('$', '').replace(',', ''))


def parse_percent(value: str) -> float:
    return float(value.replace('%', '').replace(',', ''))


parser = ReportParser()
parser.feed(INPUT_PATH.read_text())

statement = {metric: (line, value) for line, metric, value in parser.rows if value.startswith('$')}
kpis = {metric: (line, value) for line, metric, value in parser.rows if value.endswith('%')}

revenue = parse_money(statement['Revenue'][1])
expected = {
    'Gross margin': round(parse_money(statement['Gross profit'][1]) / revenue * 100, 1),
    'Operating margin': round(parse_money(statement['Operating income'][1]) / revenue * 100, 1),
    'Net margin': round(parse_money(statement['Net income'][1]) / revenue * 100, 1),
}

for metric, expected_value in expected.items():
    line, shown = kpis[metric]
    shown_value = parse_percent(shown)
    if shown_value != expected_value:
        OUTPUT_PATH.write_text(f'{line},{shown_value:g}')
        break
else:
    raise SystemExit('No incorrect KPI percentage found')
PY
