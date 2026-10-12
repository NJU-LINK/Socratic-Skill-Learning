import csv
import math
from pathlib import Path


RESULTS_CSV = Path("/app/results.csv")


def load_csv(expected_header):
    assert RESULTS_CSV.is_file(), f"{RESULTS_CSV} not found"
    with RESULTS_CSV.open(newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == expected_header
        rows = list(reader)
    assert rows, "results.csv must contain at least one data row"
    return rows


def index_unique(rows, key="fiscal_year"):
    indexed = {}
    for row in rows:
        value = row[key]
        assert value not in indexed, f"duplicate {key}: {value}"
        indexed[value] = row
    return indexed


def assert_numeric_series(indexed, column, expected, tolerance=0.011):
    assert set(indexed) == set(expected)
    for key, target in expected.items():
        raw = indexed[key][column]
        actual = float(raw)
        assert math.isfinite(actual), f"{key}: {column} is not finite"
        assert abs(actual - target) < tolerance, (
            f"{key}: expected {column}={target:.2f}, got {actual:.8g}"
        )
