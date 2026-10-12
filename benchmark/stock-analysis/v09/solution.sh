#!/bin/bash
set -e

python3 << 'PYEOF'
import csv


with open("/app/aapl_prices.csv") as stream:
    rows = list(csv.DictReader(stream))
closes = [float(row["Close"]) for row in rows]


def sma(values, period):
    return [
        None if index < period - 1
        else sum(values[index - period + 1:index + 1]) / period
        for index in range(len(values))
    ]


sma20 = sma(closes, 20)
sma50 = sma(closes, 50)
signals = []
previous_relation = None
for short, long in zip(sma20, sma50):
    if short is None or long is None:
        signals.append("N/A")
        continue
    relation = 1 if short > long else -1 if short < long else 0
    if previous_relation is None:
        label = "none"
    elif relation > 0 and previous_relation <= 0:
        label = "golden"
    elif relation < 0 and previous_relation >= 0:
        label = "death"
    else:
        label = "none"
    signals.append(label)
    previous_relation = relation

with open("/app/results.csv", "w") as output:
    output.write("date,close,sma20,sma50,cross_signal\n")
    for index, row in enumerate(rows):
        values = [row["Date"], f"{closes[index]:.2f}"]
        values.append("N/A" if sma20[index] is None else f"{sma20[index]:.2f}")
        values.append("N/A" if sma50[index] is None else f"{sma50[index]:.2f}")
        values.append(signals[index])
        output.write(",".join(values) + "\n")
PYEOF
