#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import csv
import json
import re
from pathlib import Path

INPUT = Path('/app/data/bank_transactions.csv')
OUTPUT = Path('/app/data/output.json')
FIELDS = [
    'Company Name',
    'Account Number',
    'Date',
    'Amount',
    'Transaction Type',
    'Description',
]


def normalize_name(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()


def is_target_name(name: str) -> bool:
    normalized = normalize_name(name)
    tokens = normalized.split()
    if tokens[:2] == ['nw', 'capital']:
        return True
    if 'capital' not in tokens:
        return False
    return 'north' in tokens and 'west' in tokens


def normalize_account(account: str) -> str:
    return account.upper().replace('O', '0')


with INPUT.open(newline='') as handle:
    rows = list(csv.DictReader(handle))

target_accounts = {
    normalize_account(row['Account Number'])
    for row in rows
    if is_target_name(row['Company Name'])
}

filtered = []
for row in rows:
    if is_target_name(row['Company Name']) or normalize_account(row['Account Number']) in target_accounts:
        filtered.append({field: row[field] for field in FIELDS})

filtered.sort(key=lambda row: row['Date'])
OUTPUT.write_text(json.dumps(filtered, indent=2))
PY
