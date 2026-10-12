#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from html.parser import HTMLParser
from pathlib import Path


REPORT_PATH = Path("/app/quarterly-report.html")
OUTPUT_PATH = Path("/app/value.txt")


def parse_number(text: str) -> float:
    return float(text.replace(",", "").strip())


def canonical_decimal(value: float) -> str:
    text = f"{value:.2f}"
    return text.rstrip("0").rstrip(".")


class ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tbody = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tbody":
            self.in_tbody = True
        elif self.in_tbody and tag in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []
        elif self.in_tbody and tag == "tr":
            self.current_row = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "tbody":
            self.in_tbody = False
        elif self.in_tbody and tag in {"td", "th"} and self.in_cell:
            self.current_row.append("".join(self.current_cell).strip())
            self.current_cell = []
            self.in_cell = False
        elif self.in_tbody and tag == "tr" and self.current_row:
            self.rows.append(self.current_row)
            self.current_row = []

    def handle_data(self, data: str) -> None:
        if self.in_tbody and self.in_cell:
            self.current_cell.append(data)


parser = ReportParser()
parser.feed(REPORT_PATH.read_text(encoding="utf-8"))

for row in parser.rows:
    if len(row) < 5:
        continue
    line_number, _label, current_text, prior_text, change_text = row[:5]
    expected_change = canonical_decimal(round(parse_number(current_text) - parse_number(prior_text), 2))
    reported_change = canonical_decimal(parse_number(change_text))
    if reported_change != expected_change:
        OUTPUT_PATH.write_text(f"{line_number},{change_text.strip()}\n", encoding="utf-8")
        break
else:
    raise SystemExit("No incorrect year-over-year change found")
PY
