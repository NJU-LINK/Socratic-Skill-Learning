#!/bin/bash
set -e

python3 << 'PYEOF'
import csv

rows = []
with open("/app/stock_data.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

with open("/app/results.csv", "w") as f:
    f.write("date,close,sma5,sma10\n")
    for i, r in enumerate(rows):
        close = float(r["Close"])
        if i >= 4:
            s5 = sum(float(rows[j]["Close"]) for j in range(i - 4, i + 1)) / 5
        if i >= 9:
            s10 = sum(float(rows[j]["Close"]) for j in range(i - 9, i + 1)) / 10

        out_date = r["Date"]
        out_close = f"{close:.2f}"
        out_s5 = f"{s5:.2f}" if i >= 4 else "N/A"
        out_s10 = f"{s10:.2f}" if i >= 9 else "N/A"
        f.write(f"{out_date},{out_close},{out_s5},{out_s10}\n")

print("Done")
PYEOF
