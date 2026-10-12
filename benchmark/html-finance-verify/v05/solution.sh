#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from html.parser import HTMLParser

HTML_PATH = "/app/solis_cash_flow_statement.html"
OUTPUT_PATH = "/app/answer.txt"


class CashFlowParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tbody = False
        self.in_td = False
        self.current_cell = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tbody":
            self.in_tbody = True
        elif self.in_tbody and tag == "td":
            self.in_td = True
            self.current_cell = []
        elif self.in_tbody and tag == "tr":
            self.current_row = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if tag == "tbody":
            self.in_tbody = False
        elif self.in_tbody and tag == "td":
            self.in_td = False
            self.current_row.append("".join(self.current_cell).strip())
        elif self.in_tbody and tag == "tr":
            if self.current_row:
                while len(self.current_row) < 3:
                    self.current_row.append("")
                self.rows.append(self.current_row[:3])


parser = CashFlowParser()
with open(HTML_PATH, "r", encoding="utf-8") as f:
    parser.feed(f.read())

rows = []
for line, description, amount in parser.rows:
    rows.append(
        {
            "line": line,
            "description": description,
            "amount_text": amount,
            "amount": int(amount) if amount else None,
        }
    )

section_ranges = [
    ("290", "190", "290"),
    ("490", "390", "490"),
    ("590", "495", "590"),
]

line_to_index = {row["line"]: idx for idx, row in enumerate(rows)}
candidates = []

for total_line, section_start_line, section_end_line in section_ranges:
    start = line_to_index[section_start_line]
    end = line_to_index[section_end_line]
    total_idx = line_to_index[total_line]
    detail_sum = sum(
        rows[idx]["amount"]
        for idx in range(start + 1, end)
        if rows[idx]["amount"] is not None
    )
    total_amount = rows[total_idx]["amount"]
    diff = detail_sum - total_amount
    candidates.append((abs(diff), rows[total_idx]["line"], rows[total_idx]["amount_text"]))

ending_idx = line_to_index["610"]
beginning = rows[line_to_index["100"]]["amount"]
operating = rows[line_to_index["290"]]["amount"]
investing = rows[line_to_index["490"]]["amount"]
financing = rows[line_to_index["590"]]["amount"]
fx = rows[line_to_index["600"]]["amount"]
ending = rows[ending_idx]["amount"]
reconciled_ending = beginning + operating + investing + financing + fx
candidates.append((abs(reconciled_ending - ending), rows[ending_idx]["line"], rows[ending_idx]["amount_text"]))

_, bad_line, bad_amount = max(candidates)

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(f"{bad_line},{bad_amount}\n")
PY
