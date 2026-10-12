#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import csv
import json
import re
from pathlib import Path

INPUT_PATH = Path('/app/data/bank_transactions.csv')
OUTPUT_PATH = Path('/app/data/output.json')
FIELDNAMES = [
    'Company Name',
    'Account Number',
    'Date',
    'Amount',
    'Transaction Type',
    'Description',
]


def normalize_company(name: str) -> str:
    normalized = name.lower()
    normalized = normalized.replace('&', ' and ')
    normalized = re.sub(r'[^a-z0-9]+', ' ', normalized)
    tokens = [token for token in normalized.split() if token]

    expanded = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == 'n' and index + 1 < len(tokens) and tokens[index + 1] == 'w':
            expanded.extend(['north', 'west'])
            index += 2
            continue
        if token == 'nw':
            expanded.extend(['north', 'west'])
        elif token in {'cap', 'capl', 'captl'}:
            expanded.append('capital')
        elif token in {'grp', 'group'}:
            expanded.append('group')
        elif token in {'co', 'corp', 'inc', 'llc', 'ltd'}:
            index += 1
            continue
        else:
            expanded.append(token)
        index += 1
    return ' '.join(expanded)


def is_target_name(name: str) -> bool:
    normalized = normalize_company(name)
    if 'advisor' in normalized or 'advisors' in normalized:
        return False
    return 'north west capital' in normalized


def supports_target_name(name: str) -> bool:
    normalized = normalize_company(name)
    if 'advisor' in normalized or 'advisors' in normalized:
        return False
    tokens = set(normalized.split())
    return {'north', 'west', 'capital'}.issubset(tokens)


def account_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right))


with INPUT_PATH.open(newline='') as infile:
    rows = list(csv.DictReader(infile))

anchor_accounts = {
    row['Account Number']
    for row in rows
    if is_target_name(row['Company Name'])
}

target_accounts = set(anchor_accounts)
for row in rows:
    account = row['Account Number']
    if supports_target_name(row['Company Name']) and any(
        account_distance(account, anchor) == 1 for anchor in anchor_accounts
    ):
        target_accounts.add(account)

filtered = []
for row in rows:
    if is_target_name(row['Company Name']) or row['Account Number'] in target_accounts:
        filtered.append({field: row[field] for field in FIELDNAMES})

filtered.sort(key=lambda row: row['Date'])

with OUTPUT_PATH.open('w', encoding='utf-8') as outfile:
    json.dump(filtered, outfile, indent=2)
PY
