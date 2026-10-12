#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import os
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

HTML_PATH = Path(os.environ.get('AURORA_HTML_PATH', '/app/aurora_q2_earnings.html'))
OUTPUT_PATH = Path(os.environ.get('AURORA_OUTPUT_PATH', '/app/value.txt'))


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_td = False
        self.current_text = []
        self.current_row = []
        self.tables = []
        self.current_table = []

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.current_row = []
        elif tag == 'td':
            self.in_td = True
            self.current_text = []

    def handle_data(self, data):
        if self.in_td:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'td':
            self.in_td = False
            self.current_row.append(''.join(self.current_text).strip())
        elif tag == 'tr':
            if self.current_row:
                self.current_table.append(self.current_row)
        elif tag == 'table':
            if self.current_table:
                self.tables.append(self.current_table)
            self.current_table = []


def parse_number(text: str) -> Decimal:
    return Decimal(text.replace(',', '').strip())


parser = TableParser()
parser.feed(HTML_PATH.read_text())

if len(parser.tables) < 2:
    raise SystemExit('Expected two tables in the report')

main_rows = parser.tables[0]
note_rows = parser.tables[1]

main_metrics = {}
for line_id, metric, value in main_rows:
    main_metrics[metric.split(' (')[0].strip()] = parse_number(value)

incorrect = None
for note_line, metric, displayed in note_rows:
    metric_name = metric.split(' (')[0].strip()
    if 'per share' in metric.lower():
        expected = main_metrics.get('Diluted earnings per share')
    else:
        if metric_name not in main_metrics:
            continue
        expected = main_metrics[metric_name] * Decimal('1000000')

    if parse_number(displayed) != expected:
        incorrect = (note_line, displayed)
        break

if incorrect is None:
    raise SystemExit('No inconsistent metric found')

OUTPUT_PATH.write_text(f'{incorrect[0]},{incorrect[1]}\n')
PY
