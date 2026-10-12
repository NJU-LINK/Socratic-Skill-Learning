import csv
import json
import math
from pathlib import Path


RESULTS = Path("/app/results.csv")


def load_csv_prices(filename):
    with Path("/app", filename).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    return [(row["Date"], float(row["Close"])) for row in rows]


def load_json_prices(filename):
    with Path("/app", filename).open() as stream:
        data = json.load(stream)
    return [(row["date"], float(row["close"])) for row in data["prices"]]


def load_results(expected_header):
    assert RESULTS.is_file(), f"{RESULTS} not found"
    with RESULTS.open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == expected_header
        rows = list(reader)
    assert rows, "results.csv is empty"
    return rows


def assert_source_alignment(rows, prices):
    assert len(rows) == len(prices)
    assert [row["date"] for row in rows] == [date for date, _ in prices]
    for row, (_, close) in zip(rows, prices):
        actual = float(row["close"])
        assert math.isfinite(actual)
        assert abs(actual - close) < 0.0051


def assert_numeric_series(rows, column, expected, tolerance=0.011):
    assert len(rows) == len(expected)
    for index, (row, target) in enumerate(zip(rows, expected)):
        actual = row[column]
        if target is None:
            assert actual == "N/A", f"row {index}: {column} should be N/A, got {actual}"
            continue
        assert actual != "N/A", f"row {index}: {column} unexpectedly N/A"
        value = float(actual)
        assert math.isfinite(value)
        assert abs(value - target) < tolerance, (
            f"row {index}: expected {column}={target:.8g}, got {value:.8g}"
        )


def assert_label_series(rows, column, expected):
    assert [row[column] for row in rows] == expected


def sma(values, period):
    return [
        None if index < period - 1
        else sum(values[index - period + 1:index + 1]) / period
        for index in range(len(values))
    ]


def ema(values, period):
    output = [None] * len(values)
    state = sum(values[:period]) / period
    output[period - 1] = state
    multiplier = 2 / (period + 1)
    for index in range(period, len(values)):
        state = values[index] * multiplier + state * (1 - multiplier)
        output[index] = state
    return output


def wilder_rsi(values, period=14):
    gains = [max(values[index] - values[index - 1], 0) for index in range(1, len(values))]
    losses = [max(values[index - 1] - values[index], 0) for index in range(1, len(values))]
    output = [None] * len(values)
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for index in range(period, len(values)):
        if index > period:
            average_gain = (average_gain * (period - 1) + gains[index - 1]) / period
            average_loss = (average_loss * (period - 1) + losses[index - 1]) / period
        output[index] = (
            100.0
            if average_loss == 0
            else 100 - 100 / (1 + average_gain / average_loss)
        )
    return output


def bollinger(values, period=20):
    middle = sma(values, period)
    upper = [None] * len(values)
    lower = [None] * len(values)
    for index, center in enumerate(middle):
        if center is None:
            continue
        window = values[index - period + 1:index + 1]
        deviation = math.sqrt(sum((value - center) ** 2 for value in window) / period)
        upper[index] = center + 2 * deviation
        lower[index] = center - 2 * deviation
    return middle, upper, lower


def macd(values):
    fast = ema(values, 12)
    slow = ema(values, 26)
    line = [
        None if slow[index] is None else fast[index] - slow[index]
        for index in range(len(values))
    ]
    valid_line = [value for value in line if value is not None]
    valid_signal = ema(valid_line, 9)
    signal = [None] * len(values)
    for compact_index, index in enumerate(
        index for index, value in enumerate(line) if value is not None
    ):
        signal[index] = valid_signal[compact_index]
    return line, signal


def pointwise_above(short, long):
    return [
        "N/A" if left is None or right is None else "1" if left > right else "0"
        for left, right in zip(short, long)
    ]


def crossing_labels(short, long, above_label, below_label, neutral_label):
    labels = []
    previous_relation = None
    for left, right in zip(short, long):
        if left is None or right is None:
            labels.append("N/A")
            continue
        relation = 1 if left > right else -1 if left < right else 0
        if previous_relation is None:
            label = neutral_label
        elif relation > 0 and previous_relation <= 0:
            label = above_label
        elif relation < 0 and previous_relation >= 0:
            label = below_label
        else:
            label = neutral_label
        labels.append(label)
        previous_relation = relation
    return labels
