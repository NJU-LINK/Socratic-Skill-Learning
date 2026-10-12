#!/bin/bash
set -e

python3 << 'PYEOF'
import csv

rows = []
with open("/app/aapl_prices.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

prices = [float(r["Close"]) for r in rows]
period = 14

gains, losses = [], []
for i in range(1, len(prices)):
    diff = prices[i] - prices[i-1]
    gains.append(max(diff, 0))
    losses.append(max(-diff, 0))

rsi_vals = []
for i in range(len(prices)):
    if i < period:
        rsi_vals.append(None)
    elif i == period:
        ag = sum(gains[:period]) / period
        al = sum(losses[:period]) / period
        rsi_vals.append(100.0 if al == 0 else round(100 - 100 / (1 + ag/al), 2))
    else:
        ag = (ag * (period - 1) + gains[i - 1]) / period
        al = (al * (period - 1) + losses[i - 1]) / period
        rsi_vals.append(100.0 if al == 0 else round(100 - 100 / (1 + ag/al), 2))

with open("/app/results.csv", "w") as f:
    f.write("date,close,rsi14\n")
    for i, r in enumerate(rows):
        rsi = rsi_vals[i]
        out = f"{r['Date']},{prices[i]:.2f}"
        out += f",{rsi:.2f}" if rsi is not None else ",N/A"
        f.write(out + "\n")
print("Done")
PYEOF
