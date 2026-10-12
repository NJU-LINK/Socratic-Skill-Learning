#!/bin/bash
set -e

python3 << 'PYEOF'
import csv
from openpyxl import Workbook

financial_rows = []
with open("/app/financials/msft_data.csv") as f:
    reader = csv.reader(f)
    header = next(reader)
    for row in reader:
        if row[0].startswith("FY"):
            financial_rows.append(row)

wb = Workbook()
ws = wb.active
ws.title = "MSFT Analysis"
ws.cell(row=1, column=1, value="Fiscal Year")
ws.cell(row=1, column=2, value="Revenue")
ws.cell(row=1, column=3, value="Net_Income")
ws.cell(row=1, column=4, value="Net_Margin_Pct")

for i, row in enumerate(financial_rows, start=2):
    ws.cell(row=i, column=1, value=row[0])
    ws.cell(row=i, column=2, value=float(row[1]))
    ws.cell(row=i, column=3, value=float(row[3]))
    revenue = float(row[1])
    net_income = float(row[3])
    net_margin = round((net_income / revenue) * 100, 2)
    ws.cell(row=i, column=4, value=net_margin)

wb.save("/app/msft_analysis.xlsx")
print("Done - Excel file saved")
PYEOF
