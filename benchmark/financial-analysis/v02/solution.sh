#!/bin/bash
set -e

python3 << 'PYEOF'
import os, re

financials_dir = "/app/financials"
correct_file = None

for f in sorted(os.listdir(financials_dir)):
    fp = os.path.join(financials_dir, f)
    if not os.path.isfile(fp):
        continue
    content = open(fp).read()
    if "AMD" in content and "Operating Income" in content:
        correct_file = fp
        break

if not correct_file:
    print("ERROR: Could not find AMD financial data file")
    exit(1)

print(f"Found: {correct_file}")
content = open(correct_file).read()

table_pattern = re.compile(r'<tr><td>(FY\d+)</td><td>([\d.]+)</td><td>([\d.]+)</td>', re.DOTALL)
rows = table_pattern.findall(content)

with open("/app/results.csv", "w") as f:
    f.write("fiscal_year,operating_margin_pct\n")
    for fy, rev, op_inc in rows:
        rev_f = float(rev)
        op_inc_f = float(op_inc)
        margin = (op_inc_f / rev_f) * 100
        f.write(f"{fy},{margin:.2f}\n")

print("Done")
PYEOF
