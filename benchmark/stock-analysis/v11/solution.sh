#!/bin/bash
set -e

python3 << 'PYEOF'
import csv


with open("/app/googl_prices.csv") as stream:
    rows = list(csv.DictReader(stream))
closes = [float(row["Close"]) for row in rows]


def ema(values, period):
    output = [None] * len(values)
    state = sum(values[:period]) / period
    output[period - 1] = state
    multiplier = 2 / (period + 1)
    for index in range(period, len(values)):
        state = values[index] * multiplier + state * (1 - multiplier)
        output[index] = state
    return output


ema12 = ema(closes, 12)
ema26 = ema(closes, 26)
macd = [
    None if ema26[index] is None else ema12[index] - ema26[index]
    for index in range(len(closes))
]
valid_macd = [value for value in macd if value is not None]
valid_signal = ema(valid_macd, 9)
signal = [None] * len(closes)
for compact_index, index in enumerate(
    index for index, value in enumerate(macd) if value is not None
):
    signal[index] = valid_signal[compact_index]

actions = []
previous_relation = None
for line, trigger in zip(macd, signal):
    if line is None or trigger is None:
        actions.append("N/A")
        continue
    relation = 1 if line > trigger else -1 if line < trigger else 0
    if previous_relation is None:
        action = "hold"
    elif relation > 0 and previous_relation <= 0:
        action = "buy"
    elif relation < 0 and previous_relation >= 0:
        action = "sell"
    else:
        action = "hold"
    actions.append(action)
    previous_relation = relation

with open("/app/results.csv", "w") as output:
    output.write("date,close,macd,signal,action\n")
    for index, row in enumerate(rows):
        values = [row["Date"], f"{closes[index]:.2f}"]
        values.append("N/A" if macd[index] is None else f"{macd[index]:.2f}")
        values.append("N/A" if signal[index] is None else f"{signal[index]:.2f}")
        values.append(actions[index])
        output.write(",".join(values) + "\n")
PYEOF
