#!/bin/bash
set -e

python3 << 'PYEOF'
import csv

rows = []
with open("/app/googl_prices.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

with open("/app/results.csv", "w") as f:
    f.write("date,close,sma5,sma10,signal\n")
    for i, r in enumerate(rows):
        close = float(r["Close"])
        s5 = sum(float(rows[j]["Close"]) for j in range(i-4, i+1)) / 5 if i >= 4 else None
        s10 = sum(float(rows[j]["Close"]) for j in range(i-9, i+1)) / 10 if i >= 9 else None
        sig = 1 if (s5 and s10 and s5 > s10) else (0 if (s5 and s10) else None)
        out = f"{r['Date']},{close:.2f}"
        out += f",{s5:.2f}" if s5 is not None else ",N/A"
        out += f",{s10:.2f}" if s10 is not None else ",N/A"
        out += f",{sig}" if sig is not None else ",N/A"
        f.write(out + "\n")
print("Done")
PYEOF
