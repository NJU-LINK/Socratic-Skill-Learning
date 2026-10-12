#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from html.parser import HTMLParser
from pathlib import Path


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_td = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.in_td = True
            self.current_cell = []
        elif tag == "tr":
            self.current_row = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            self.in_td = False
            self.current_row.append("".join(self.current_cell).strip())
        elif tag == "tr" and len(self.current_row) == 3:
            self.rows.append(tuple(self.current_row))


def parse_value(raw: str) -> int:
    return int(raw.replace(",", "").strip())


html_path = Path("/app/annual-report.html")
parser = ReportParser()
parser.feed(html_path.read_text(encoding="utf-8"))

detail_rows = []
for line, label, value in parser.rows:
    if "subtotal" in label.lower():
        detail_rows.append((int(line), label, parse_value(value), True))
    elif "revenue" not in label.lower():
        detail_rows.append((int(line), label, parse_value(value), False))

running_total = 0
for line, label, value, is_subtotal in detail_rows:
    if is_subtotal:
        if running_total != value:
            Path("/app/value.txt").write_text(f"{line},{value}", encoding="utf-8")
            break
        running_total = 0
    else:
        running_total += value
else:
    raise SystemExit("No inconsistent subtotal found")
PY
