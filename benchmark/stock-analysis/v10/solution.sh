#!/bin/bash
set -e

python3 << 'PYEOF'
import csv


with open("/app/msft_prices.csv") as stream:
    rows = list(csv.DictReader(stream))
closes = [float(row["Close"]) for row in rows]
period = 14

gains = [max(closes[index] - closes[index - 1], 0) for index in range(1, len(closes))]
losses = [max(closes[index - 1] - closes[index], 0) for index in range(1, len(closes))]
rsi = [None] * len(closes)
average_gain = sum(gains[:period]) / period
average_loss = sum(losses[:period]) / period
for index in range(period, len(closes)):
    if index > period:
        average_gain = (average_gain * (period - 1) + gains[index - 1]) / period
        average_loss = (average_loss * (period - 1) + losses[index - 1]) / period
    rsi[index] = (
        100.0
        if average_loss == 0
        else 100 - 100 / (1 + average_gain / average_loss)
    )

with open("/app/results.csv", "w") as output:
    output.write("date,close,rsi14,signal\n")
    for index, row in enumerate(rows):
        if rsi[index] is None:
            output.write(f'{row["Date"]},{closes[index]:.2f},N/A,N/A\n')
            continue
        label = "overbought" if rsi[index] > 70 else "oversold" if rsi[index] < 30 else "neutral"
        output.write(f'{row["Date"]},{closes[index]:.2f},{rsi[index]:.2f},{label}\n')
PYEOF
