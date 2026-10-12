import csv
import json
from pathlib import Path


INPUT_PATH = Path('/app/data/bank_transactions.csv')
OUTPUT_PATH = Path('/app/data/output.json')
EXPECTED_KEYS = [
    'Company Name',
    'Account Number',
    'Date',
    'Amount',
    'Transaction Type',
    'Description',
]
EXPECTED_ROWS = [3, 5, 7, 9, 10, 12, 16, 17, 19, 21, 23, 24, 25, 27]


def load_csv_rows():
    with INPUT_PATH.open(newline='') as handle:
        return list(csv.DictReader(handle))


def load_output():
    with OUTPUT_PATH.open() as handle:
        return json.load(handle)


def test_output_matches_expected_rows_exactly():
    csv_rows = load_csv_rows()
    expected = [csv_rows[index - 2] for index in EXPECTED_ROWS]
    assert load_output() == expected


def test_output_schema_and_sorting_are_correct():
    output = load_output()

    assert isinstance(output, list)
    assert [row['Date'] for row in output] == sorted(row['Date'] for row in output)

    for row in output:
        assert list(row.keys()) == EXPECTED_KEYS
        assert all(isinstance(value, str) for value in row.values())


def test_lookalike_accounts_and_companies_are_excluded():
    output = load_output()
    account_numbers = {row['Account Number'] for row in output}
    company_names = {row['Company Name'] for row in output}
    descriptions = {row['Description'] for row in output}

    assert 'BUS-3000I' not in account_numbers
    assert 'BUS-3500I' not in account_numbers
    assert 'BUS-3500l' not in account_numbers
    assert 'BUS-3200I' not in account_numbers
    assert 'BUS-32OO1' not in account_numbers
    assert 'Northwind Cargo LLC' not in company_names
    assert 'Harbor Freight Systems' not in company_names
    assert 'Delta Marine Supply' not in company_names
    assert 'Norlight Transport' not in company_names
    assert 'Compliance Filing' not in descriptions
