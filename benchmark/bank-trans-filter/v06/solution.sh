#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import csv
import json
import re
from pathlib import Path

INPUT_PATH = Path('/app/data/bank_transactions.csv')
OUTPUT_PATH = Path('/app/data/output.json')


def normalize_name(value: str) -> list[str]:
    return [token for token in re.sub(r'[^a-z0-9]+', ' ', value.lower()).split() if token]


def is_target_anchor(name: str) -> bool:
    tokens = normalize_name(name)
    token_set = set(tokens)
    joined = ''.join(tokens)
    has_capital = 'capital' in token_set or 'cap' in token_set or 'northwestcap' in joined
    has_north_west = (
        'northwest' in token_set
        or 'northwest' in joined
        or ('north' in token_set and 'west' in token_set)
        or ('n' in token_set and 'w' in token_set)
    )
    return has_capital and has_north_west


def o_zero_distance(left: str, right: str) -> int | None:
    if len(left) != len(right):
        return None

    differences = 0
    for left_char, right_char in zip(left, right):
        if left_char == right_char:
            continue
        if {left_char, right_char} != {'0', 'O'}:
            return None
        differences += 1
    return differences


with INPUT_PATH.open(newline='') as handle:
    rows = list(csv.DictReader(handle))

anchor_accounts = {
    row['Account Number']
    for row in rows
    if is_target_anchor(row['Company Name'])
}

selected_rows = []
for row in rows:
    account = row['Account Number']
    if account in anchor_accounts:
        selected_rows.append(row)
        continue

    if any(o_zero_distance(account, target_account) == 1 for target_account in anchor_accounts):
        selected_rows.append(row)

selected_rows.sort(key=lambda row: row['Date'])

OUTPUT_PATH.write_text(json.dumps(selected_rows, indent=2))
PY
