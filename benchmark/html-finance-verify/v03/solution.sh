#!/bin/bash
set -euo pipefail

cd /app

python3 - <<'PY'
from decimal import Decimal, ROUND_HALF_UP
from html.parser import HTMLParser
from pathlib import Path


class ReconciliationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.current_text = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.current_text = []

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.in_row and self.in_cell:
            text = " ".join("".join(self.current_text).split())
            self.current_row.append(text)
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False

    def handle_data(self, data):
        if self.in_cell:
            self.current_text.append(data)


def parse_value(text: str) -> Decimal:
    cleaned = text.strip().replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        return -Decimal(cleaned[1:-1])
    return Decimal(cleaned)


def normalize_reported(text: str) -> str:
    cleaned = text.strip().replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        return f"-{cleaned[1:-1]}"
    return cleaned


html = Path("/app/earnings-reconciliation.html").read_text(encoding="utf-8")
parser = ReconciliationParser()
parser.feed(html)

rows = []
for row in parser.rows:
    if len(row) != 3 or not row[0].isdigit():
        continue
    rows.append({
        "line": int(row[0]),
        "description": row[1],
        "reported": row[2],
        "value": parse_value(row[2]),
    })


def find_row(*terms: str):
    lowered_terms = [term.lower() for term in terms]
    for row in rows:
        description = row["description"].lower()
        if all(term in description for term in lowered_terms):
            return row
    raise SystemExit(f"Missing row matching {terms}")


gaap_row = find_row("gaap", "net income")
adjusted_row = find_row("adjusted", "net income")
shares_row = find_row("weighted-average", "shares")
eps_row = find_row("per share")

gaap_index = rows.index(gaap_row)
adjusted_index = rows.index(adjusted_row)
adjustment_rows = rows[gaap_index + 1:adjusted_index]
expected_adjusted = gaap_row["value"] + sum((row["value"] for row in adjustment_rows), Decimal("0"))
expected_eps = (adjusted_row["value"] / shares_row["value"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

income_consistent = adjusted_row["value"] == expected_adjusted
eps_consistent = eps_row["value"] == expected_eps

if not income_consistent and eps_consistent:
    wrong_row = adjusted_row
elif income_consistent and not eps_consistent:
    wrong_row = eps_row
else:
    raise SystemExit("Could not identify a unique incorrect metric")

Path("/app/value.txt").write_text(
    f"{wrong_row['line']},{normalize_reported(wrong_row['reported'])}\n",
    encoding="utf-8",
)
PY
