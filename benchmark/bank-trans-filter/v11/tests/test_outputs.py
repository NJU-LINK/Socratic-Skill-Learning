import csv
import json
from pathlib import Path


INPUT_CSV = Path('/app/data/bank_transactions.csv')
OUTPUT_JSON = Path('/app/data/output.json')
EXPECTED_KEYS = [
    'Company Name',
    'Account Number',
    'Date',
    'Amount',
    'Transaction Type',
    'Description',
]
EXPECTED_ROWS = [
    {
        'Company Name': 'North West Cap. Group',
        'Account Number': 'BUS-30001',
        'Date': '2024-01-22',
        'Amount': '-$197887.00',
        'Transaction Type': 'Payment',
        'Description': 'Professional Services',
    },
    {
        'Company Name': 'N.W. Capital Group Inc',
        'Account Number': 'BUS-30g01',
        'Date': '2024-02-02',
        'Amount': '-$56760.00',
        'Transaction Type': 'Payment',
        'Description': 'Consulting Fee',
    },
    {
        'Company Name': 'North-West Capital',
        'Account Number': 'BUS-30001',
        'Date': '2024-03-01',
        'Amount': '-$84377.00',
        'Transaction Type': 'Purchase',
        'Description': 'Office Supplies',
    },
    {
        'Company Name': 'North West Capital',
        'Account Number': 'BUS-30001',
        'Date': '2024-03-15',
        'Amount': '-$22413.00',
        'Transaction Type': 'Withdrawal',
        'Description': 'Office Supplies',
    },
    {
        'Company Name': 'N.W. Capital Group Inc',
        'Account Number': 'BUS-30001',
        'Date': '2024-03-16',
        'Amount': '-$205706.00',
        'Transaction Type': 'Purchase',
        'Description': 'Software License',
    },
    {
        'Company Name': 'North West Capital',
        'Account Number': 'BUS-30001',
        'Date': '2024-03-20',
        'Amount': '$232005.00',
        'Transaction Type': 'Deposit',
        'Description': 'Quarterly Earnings',
    },
    {
        'Company Name': 'North West Cap. Group',
        'Account Number': 'BUS-30001',
        'Date': '2024-04-04',
        'Amount': '$279375.00',
        'Transaction Type': 'Transfer',
        'Description': 'Inter-company Transfer',
    },
    {
        'Company Name': 'North-West Capital',
        'Account Number': 'BUS-30001',
        'Date': '2024-04-10',
        'Amount': '-$125251.00',
        'Transaction Type': 'Withdrawal',
        'Description': 'Payroll',
    },
    {
        'Company Name': 'North West Capital',
        'Account Number': 'BUS-30001',
        'Date': '2024-04-13',
        'Amount': '$121274.00',
        'Transaction Type': 'Transfer',
        'Description': 'Partner Distribution',
    },
]


def load_output():
    return json.loads(OUTPUT_JSON.read_text(encoding='utf-8'))


def test_output_is_json_array_with_expected_rows():
    assert OUTPUT_JSON.exists(), 'output.json was not created'
    data = load_output()
    assert isinstance(data, list)
    assert data == EXPECTED_ROWS


def test_output_rows_preserve_exact_csv_strings_and_key_order():
    with INPUT_CSV.open(newline='') as infile:
        csv_rows = [row for row in csv.DictReader(infile)]
    csv_row_set = {tuple(row[key] for key in EXPECTED_KEYS) for row in csv_rows}

    for row in load_output():
        assert list(row.keys()) == EXPECTED_KEYS
        assert tuple(row[key] for key in EXPECTED_KEYS) in csv_row_set


def test_output_is_sorted_and_excludes_distractor_cluster():
    data = load_output()
    dates = [row['Date'] for row in data]
    assert dates == sorted(dates)

    assert all('Advisor' not in row['Company Name'] for row in data)
    assert all(not row['Company Name'].startswith('Northwest Cap Advisors') for row in data)
    assert {row['Account Number'] for row in data} == {'BUS-30001', 'BUS-30g01'}
