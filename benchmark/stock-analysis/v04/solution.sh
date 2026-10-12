#!/bin/bash
set -e

python3 << 'PYEOF'
import csv


with open("/app/tsla_prices.csv") as stream:
    rows = list(csv.DictReader(stream))
closes = [float(row["Close"]) for row in rows]


def ema(values, period):
    output = [None] * len(values)
    seed_index = period - 1
    state = sum(values[:period]) / period
    output[seed_index] = state
    multiplier = 2 / (period + 1)
    for index in range(period, len(values)):
        state = values[index] * multiplier + state * (1 - multiplier)
        output[index] = state
    return output


ema12 = ema(closes, 12)
ema26 = ema(closes, 26)
with open("/app/results.csv", "w") as output:
    output.write("date,close,ema12,ema26\n")
    for index, row in enumerate(rows):
        values = [row["Date"], f"{closes[index]:.2f}"]
        values.append("N/A" if ema12[index] is None else f"{ema12[index]:.2f}")
        values.append("N/A" if ema26[index] is None else f"{ema26[index]:.2f}")
        output.write(",".join(values) + "\n")
PYEOF
