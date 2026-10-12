#!/bin/bash
set -e

python3 << 'PYEOF'
import csv, os

financials_dir = "/app/financials"
bs_file = is_file = None

for f in os.listdir(financials_dir):
    fp = os.path.join(financials_dir, f)
    if not os.path.isfile(fp):
        continue
    content = open(fp, encoding="utf-8").read()
    if "股东权益合计" in content:
        bs_file = fp
    if "净利润" in content and "营业收入" in content:
        is_file = fp

if not bs_file or not is_file:
    print("ERROR: Could not find BS or IS file")
    exit(1)

net_profit = {}
with open(is_file, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if "净利润" in row["项目"]:
            for k, v in row.items():
                if k != "项目":
                    net_profit[k] = float(v)

equity = {}
with open(bs_file, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if "股东权益合计" in row["项目"] or "股东权益" in row["项目"]:
            for k, v in row.items():
                if k != "项目":
                    equity[k] = float(v)

with open("/app/results.csv", "w") as f:
    f.write("fiscal_year,roe_pct\n")
    for fy in sorted(equity.keys()):
        if fy in net_profit:
            roe = (net_profit[fy] / equity[fy]) * 100
            f.write(f"FY{fy},{roe:.2f}\n")

print("Done")
PYEOF
