#!/bin/bash
set -e

python3 << 'PYEOF'
import re

with open("/app/financials/wuliangye_financials.html", encoding="utf-8") as f:
    html = f.read()

pattern = re.compile(r"<tr><td>(FY\d+)</td><td>([\d.]+)</td><td>([\d.]+)</td>")
rows = pattern.findall(html)

with open("/app/results.csv", "w") as f:
    f.write("fiscal_year,operating_margin_pct\n")
    for fy, rev, op in rows:
        margin = (float(op) / float(rev)) * 100
        f.write(f"{fy},{margin:.2f}\n")

print("Done")
PYEOF
