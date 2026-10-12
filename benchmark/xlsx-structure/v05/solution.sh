#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import openpyxl

source = "/app/input.xlsx"
target = "/app/output.xlsx"
workbook = openpyxl.load_workbook(source)
sheet = workbook["Sheet1"]

allowed = {
    sheet.cell(row, 6).value
    for row in range(2, sheet.max_row + 1)
    if sheet.cell(row, 6).value not in (None, "")
}
kept = [
    [sheet.cell(row, column).value for column in range(1, 4)]
    for row in range(2, sheet.max_row + 1)
    if sheet.cell(row, 1).value in allowed
]

for row in range(2, sheet.max_row + 1):
    for column in range(1, 4):
        sheet.cell(row, column).value = None
for row, values in enumerate(kept, start=2):
    for column, value in enumerate(values, start=1):
        sheet.cell(row, column).value = value

workbook.save(target)
PY
