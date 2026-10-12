#!/bin/bash
set -euo pipefail

python3 <<'PY'
import csv
import json
import re
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
REJECT_PATTERNS = ('advis', 'hold', 'northwestern')


def normalized_tokens(name: str) -> list[str]:
    cleaned = re.sub(r'[^a-z0-9]+', ' ', name.lower())
    aliases = {
        'nrth': ['north'],
        'n': ['north'],
        'wst': ['west'],
        'w': ['west'],
        'cptl': ['capital'],
        'cap': ['capital'],
        'grp': ['group'],
        'grop': ['group'],
        'gp': ['group'],
        'incorporated': ['inc'],
        'incoporated': ['inc'],
        'nwc': ['north', 'west', 'capital'],
        'northwest': ['north', 'west'],
    }
    tokens = []
    for token in cleaned.split():
        tokens.extend(aliases.get(token, [token]))
    return tokens


def is_target_like(name: str) -> bool:
    compact = re.sub(r'[^a-z0-9]+', '', name.lower())
    if any(pattern in compact for pattern in REJECT_PATTERNS):
        return False

    tokens = normalized_tokens(name)
    token_set = set(tokens)
    return {'north', 'west', 'capital'}.issubset(token_set)


with INPUT_PATH.open(newline='', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

anchor_accounts = {
    row['Account Number']
    for row in rows
    if is_target_like(row['Company Name'])
}

target_rows = []
for row in rows:
    if row['Account Number'] in anchor_accounts or is_target_like(row['Company Name']):
        target_rows.append({key: row[key] for key in EXPECTED_KEYS})

target_rows.sort(key=lambda row: row['Date'])
OUTPUT_PATH.write_text(json.dumps(target_rows, indent=2), encoding='utf-8')
PY
