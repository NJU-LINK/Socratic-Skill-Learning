#!/bin/bash
set -euo pipefail

python3 <<'PY'
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tbody":
            self.in_tbody = True
        elif self.in_tbody and tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_tr and tag == "td":
            self.in_td = True
            self.current_cell = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            self.current_row.append("".join(self.current_cell).strip())
            self.in_td = False
        elif tag == "tr" and self.in_tr:
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_tr = False
        elif tag == "tbody":
            self.in_tbody = False


def parse_rows(path: Path):
    parser = ReportParser()
    parser.feed(path.read_text())
    values = {}
    raw_values = {}
    for row in parser.rows:
        if len(row) < 3:
            continue
        line = row[0]
        raw = row[2]
        raw_values[line] = raw
        values[line] = Decimal(raw)
    return values, raw_values


values, raw_values = parse_rows(Path("/app/earnings-report.html"))

checks = [
    ("5240", values["5210"] + values["5220"] + values["5230"]),
    ("5290", values["5260"] + values["5270"] + values["5280"]),
    ("5300", values["5240"] - values["5290"]),
    ("5350", values["5320"] + values["5330"] + values["5340"]),
    ("5360", values["5300"] - values["5350"]),
    ("5400", values["5360"] + values["5380"] + values["5390"]),
    ("5420", values["5400"] - values["5410"]),
]

for line, expected in checks:
    if values[line] != expected:
        Path("/app/value.txt").write_text(f"{line},{raw_values[line]}\n")
        break
else:
    raise SystemExit("no inconsistent subtotal found")
PY
