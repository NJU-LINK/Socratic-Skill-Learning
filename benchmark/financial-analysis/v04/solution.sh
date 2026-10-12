#!/bin/bash
set -e

python3 << 'PYEOF'
# Read income data
income = {}
with open("/app/income.csv") as f:
    header = f.readline()
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        fy = parts[0]
        revenue = float(parts[1])
        net_income = float(parts[2])
        income[fy] = net_income

# Read equity data
equity = {}
with open("/app/balance/equity.csv") as f:
    header = f.readline()
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        fy = parts[0]
        total_equity = float(parts[1])
        equity[fy] = total_equity

# Cross-reference and compute ROE
with open("/app/results.csv", "w") as f:
    f.write("fiscal_year,roe_pct\n")
    for fy in sorted(set(list(income.keys()) + list(equity.keys()))):
        if fy in income and fy in equity:
            roe = (income[fy] / equity[fy]) * 100
            f.write(f"{fy},{roe:.2f}\n")

print("Done")
PYEOF
