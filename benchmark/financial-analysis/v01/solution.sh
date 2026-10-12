#!/bin/bash
set -e

python3 << 'PYEOF'
import csv
import os

financials_dir = "/app/financials"
data_file = None
for name in sorted(os.listdir(financials_dir)):
    candidate = os.path.join(financials_dir, name)
    if not os.path.isfile(candidate):
        continue
    content = open(candidate).read()
    if "NVIDIA Corporation" in content and "GrossProfit" in content:
        data_file = candidate
        break

if data_file is None:
    raise SystemExit("Could not find NVIDIA annual financial data")

lines = open(data_file).read().splitlines()
header_index = next(
    index for index, line in enumerate(lines)
    if line.strip().startswith("Year,Revenue,")
)
records = []
for row in csv.DictReader(lines[header_index:]):
    fiscal_year = (row.get("Year") or "").strip()
    if not fiscal_year.startswith("FY"):
        continue
    records.append({
        "fiscal_year": fiscal_year,
        "revenue": float(row["Revenue"]),
        "gross_profit": float(row["GrossProfit"]),
        "net_income": float(row["NetIncome"]),
    })

if not records:
    raise SystemExit("No annual records found")

latest = max(records, key=lambda record: int(record["fiscal_year"].removeprefix("FY")))
use_gross_margin = latest["gross_profit"] / latest["revenue"] * 100 > 70
metric = "gross_margin_pct" if use_gross_margin else "net_margin_pct"
numerator = "gross_profit" if use_gross_margin else "net_income"

with open("/app/results.csv", "w") as output:
    output.write(f"fiscal_year,{metric}\n")
    for record in records:
        value = record[numerator] / record["revenue"] * 100
        output.write(f'{record["fiscal_year"]},{value:.2f}\n')
PYEOF
