import json
from pathlib import Path


OUTPUT_PATH = Path('/app/data/output.json')
EXPECTED = [
    {
        'Company Name': 'North West Capital Ltd',
        'Account Number': 'BUS-41001',
        'Date': '2024-01-06',
        'Amount': '$125000.00',
        'Transaction Type': 'Deposit',
        'Description': 'Quarterly Earnings',
    },
    {
        'Company Name': 'NW Capital',
        'Account Number': 'BUS-410O1',
        'Date': '2024-01-10',
        'Amount': '-$6420.00',
        'Transaction Type': 'Payment',
        'Description': 'Software License',
    },
    {
        'Company Name': 'North West Capital Group',
        'Account Number': 'BUS-41001',
        'Date': '2024-01-14',
        'Amount': '-$12990.00',
        'Transaction Type': 'Withdrawal',
        'Description': 'Office Supplies',
    },
    {
        'Company Name': 'North West Capital',
        'Account Number': 'BUS-41001',
        'Date': '2024-01-18',
        'Amount': '$34650.00',
        'Transaction Type': 'Transfer',
        'Description': 'Account Consolidation',
    },
    {
        'Company Name': 'North West Capital Ltd',
        'Account Number': 'BUS-41001',
        'Date': '2024-01-22',
        'Amount': '-$7850.00',
        'Transaction Type': 'Payment',
        'Description': 'Vendor Payment',
    },
    {
        'Company Name': 'North West Capital Group',
        'Account Number': 'BUS-41001',
        'Date': '2024-01-27',
        'Amount': '$22140.00',
        'Transaction Type': 'Deposit',
        'Description': 'Contract Payment',
    },
    {
        'Company Name': 'NW Capital',
        'Account Number': 'BUS-41001',
        'Date': '2024-02-03',
        'Amount': '-$14440.00',
        'Transaction Type': 'Purchase',
        'Description': 'Insurance Premium',
    },
    {
        'Company Name': 'North West Capital Ltd',
        'Account Number': 'BUS-41001',
        'Date': '2024-02-05',
        'Amount': '$57220.00',
        'Transaction Type': 'Deposit',
        'Description': 'Service Income',
    },
    {
        'Company Name': 'North West Capital',
        'Account Number': 'BUS-41001',
        'Date': '2024-02-09',
        'Amount': '-$9600.00',
        'Transaction Type': 'Payment',
        'Description': 'Legal Services',
    },
    {
        'Company Name': 'North West Capital Group',
        'Account Number': 'BUS-41001',
        'Date': '2024-02-12',
        'Amount': '$88100.00',
        'Transaction Type': 'Transfer',
        'Description': 'Capital Movement',
    },
    {
        'Company Name': 'NW Capital',
        'Account Number': 'BUS-41001',
        'Date': '2024-02-15',
        'Amount': '-$5250.00',
        'Transaction Type': 'Withdrawal',
        'Description': 'Rent Payment',
    },
    {
        'Company Name': 'North West Capital Ltd',
        'Account Number': 'BUS-41001',
        'Date': '2024-02-21',
        'Amount': '$49210.00',
        'Transaction Type': 'Deposit',
        'Description': 'Revenue Payment',
    },
]


def test_output_matches_expected_transactions():
    assert OUTPUT_PATH.exists(), 'Expected /app/data/output.json to be created'
    actual = json.loads(OUTPUT_PATH.read_text())
    assert actual == EXPECTED


def test_output_shape_and_sort_order():
    actual = json.loads(OUTPUT_PATH.read_text())
    assert isinstance(actual, list)
    assert all(list(row) == list(EXPECTED[0]) for row in actual)
    assert [row['Date'] for row in actual] == sorted(row['Date'] for row in actual)


def test_distractors_are_excluded():
    actual = json.loads(OUTPUT_PATH.read_text())
    names = {row['Company Name'] for row in actual}
    accounts = {row['Account Number'] for row in actual}
    assert 'Northwest Logistics Capital' not in names
    assert 'West Capital Ventures' not in names
    assert 'Northern Capital Group' not in names
    assert 'BUS-48112' not in accounts
    assert 'BUS-56220' not in accounts
    assert 'BUS-77109' not in accounts
