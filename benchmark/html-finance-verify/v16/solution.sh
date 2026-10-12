#!/bin/bash
set -euo pipefail

cd /app

python3 - <<'PY'
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False
        self._current_table = None
        self._current_row = None
        self._cell_parts = None
        self._current_cell_tag = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._current_row = []
        elif self._current_row is not None and tag in {"td", "th"}:
            self._current_cell_tag = tag
            self._cell_parts = []

    def handle_data(self, data):
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag):
        if self._current_row is not None and tag in {"td", "th"} and self._cell_parts is not None:
            text = " ".join(part.strip() for part in self._cell_parts if part.strip())
            self._current_row.append((self._current_cell_tag, text))
            self._cell_parts = None
            self._current_cell_tag = None
        elif self._in_table and tag == "tr" and self._current_row is not None:
            self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._in_table:
            headers = []
            rows = []
            for row in self._current_table:
                values = [value for _, value in row]
                tags = [cell_tag for cell_tag, _ in row]
                if values and all(cell_tag == "th" for cell_tag in tags) and not headers:
                    headers = values
                elif values:
                    rows.append(values)
            self.tables.append(Table(headers=headers, rows=rows))
            self._in_table = False
            self._current_table = None


def parse_amount(text: str) -> float:
    return float(text.replace(",", "").strip())


def is_amount(text: str) -> bool:
    return re.fullmatch(r"-?\d+(?:,\d{3})*(?:\.\d+)?", text.strip()) is not None


def pick_current_period_index(table: Table) -> int:
    for index, header in enumerate(table.headers):
        if index == 0:
            continue
        if re.search(r"Q\d", header) or re.search(r"FY\d{4}", header):
            return index
    raise ValueError(f"Could not identify period column in headers: {table.headers!r}")


def find_consolidated_row(tables: list[Table]):
    for table in tables:
        if not table.rows:
            continue
        period_index = pick_current_period_index(table)
        for row in table.rows:
            if len(row) <= period_index:
                continue
            label = " ".join(row[1:2]).strip().lower() if len(row) > 1 else ""
            if "consolidated revenue" in label and is_amount(row[period_index]):
                return row[0].strip(), row[period_index].strip()
    raise ValueError("Could not find consolidated revenue row")


def find_segment_total_row(tables: list[Table]):
    for table in tables:
        if not table.rows:
            continue
        period_index = pick_current_period_index(table)
        amount_rows = []
        for row in table.rows:
            if len(row) <= period_index or len(row) < 2:
                continue
            if not row[0].strip().isdigit() or not is_amount(row[period_index]):
                continue
            amount_rows.append(row)

        for index, row in enumerate(amount_rows):
            label = row[1].strip().lower()
            if "total" not in label:
                continue

            component_rows = []
            for candidate in amount_rows[:index]:
                candidate_label = candidate[1].strip().lower()
                if "total" in candidate_label:
                    continue
                component_rows.append(candidate)

            if len(component_rows) < 2:
                continue

            return component_rows, row[0].strip(), row[period_index].strip()

    raise ValueError("Could not find segment total row")


html_path = Path("/app/aurora-q2-report.html")
parser = TableParser()
parser.feed(html_path.read_text(encoding="utf-8"))

consolidated_line, consolidated_value = find_consolidated_row(parser.tables)
component_rows, total_line, total_value = find_segment_total_row(parser.tables)
period_index = pick_current_period_index(next(table for table in parser.tables if any(row and row[0].strip() == total_line for row in table.rows)))
component_sum = round(sum(parse_amount(row[period_index]) for row in component_rows), 1)

candidates = []
if abs(component_sum - parse_amount(total_value)) > 0.1:
    candidates.append((total_line, total_value))
if abs(component_sum - parse_amount(consolidated_value)) > 0.1:
    candidates.append((consolidated_line, consolidated_value))

if len(candidates) != 1:
    raise SystemExit(f"Expected exactly one incorrect metric, found {candidates!r}")

Path("/app/value.txt").write_text(f"{candidates[0][0]},{candidates[0][1]}\n", encoding="utf-8")
PY
