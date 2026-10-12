import csv
import json
from collections import Counter
from pathlib import Path


INPUT_PATH = Path("/app/data/bank_transactions.csv")
OUTPUT_PATH = Path("/app/data/output.json")
EXPECTED_KEYS = [
    "Company Name",
    "Account Number",
    "Date",
    "Amount",
    "Transaction Type",
    "Description",
]


def source_rows():
    with INPUT_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def output_rows():
    assert OUTPUT_PATH.is_file(), f"missing output file: {OUTPUT_PATH}"
    with OUTPUT_PATH.open(encoding="utf-8") as handle:
        output = json.load(handle)
    assert isinstance(output, list), "output must be a top-level JSON array"
    return output


def expected_rows(csv_line_numbers):
    rows = source_rows()
    selected = [rows[line_number - 2] for line_number in csv_line_numbers]
    return sorted(selected, key=lambda row: row["Date"])


def row_counter(rows):
    return Counter(tuple(row[key] for key in EXPECTED_KEYS) for row in rows)


def assert_valid_artifact():
    output_rows()


def assert_complete(csv_line_numbers):
    expected = row_counter(expected_rows(csv_line_numbers))
    actual = row_counter(output_rows())
    assert not expected - actual, "missing target transactions"


def assert_precise(csv_line_numbers):
    expected = row_counter(expected_rows(csv_line_numbers))
    actual = row_counter(output_rows())
    assert not actual - expected, "included non-target transactions"


def assert_exact_and_sorted(csv_line_numbers):
    assert output_rows() == expected_rows(csv_line_numbers)


def assert_schema_and_source_preservation():
    source = row_counter(source_rows())
    for row in output_rows():
        assert list(row) == EXPECTED_KEYS
        assert all(isinstance(value, str) for value in row.values())
        assert row_counter([row]) <= source


def assert_identity_variation_is_covered(csv_line_numbers):
    expected = expected_rows(csv_line_numbers)
    output = output_rows()
    expected_names = {row["Company Name"] for row in expected}
    expected_accounts = {row["Account Number"] for row in expected}
    assert len(expected_names) > 1 or len(expected_accounts) > 1
    assert {row["Company Name"] for row in output} == expected_names
    assert {row["Account Number"] for row in output} == expected_accounts
