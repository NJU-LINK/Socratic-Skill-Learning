#!/bin/bash
set -e

python3 << 'PYEOF'
import csv, math

rows = []
with open("/app/googl_prices.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)
prices = [float(r["Close"]) for r in rows]
period = 20

with open("/app/results.csv", "w") as f:
    f.write("date,close,middle,upper,lower\n")
    for i in range(len(rows)):
        if i < period - 1:
            f.write(f"{rows[i]['Date']},{prices[i]:.2f},N/A,N/A,N/A\n")
        else:
            window = prices[i - period + 1 : i + 1]
            mid = sum(window) / period
            var = sum((x - mid) ** 2 for x in window) / period
            std = math.sqrt(var)
            upper = mid + 2 * std
            lower = mid - 2 * std
            f.write(f"{rows[i]['Date']},{prices[i]:.2f},{mid:.2f},{upper:.2f},{lower:.2f}\n")
print("Done")
PYEOF
