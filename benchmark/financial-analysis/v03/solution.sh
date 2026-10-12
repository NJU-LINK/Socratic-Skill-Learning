#!/bin/bash
set -e

python3 << 'PYEOF'
import json

with open("/app/financials/intel_data.json") as f:
    data = json.load(f)

records = data["intel_financials"]

with open("/app/results.csv", "w") as f:
    f.write("fiscal_year,net_income_growth_pct\n")
    for i, rec in enumerate(records):
        fy = rec["fiscal_year"]
        ni = rec["Net_Income"]
        if i == 0:
            f.write(f"{fy},N/A\n")
        else:
            prev_ni = records[i-1]["Net_Income"]
            growth = ((ni - prev_ni) / abs(prev_ni)) * 100
            f.write(f"{fy},{growth:.2f}\n")

print("Done")
PYEOF
