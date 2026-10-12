#!/bin/bash
set -euo pipefail

python3 - <<'PY'
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

INPUT_PATH = Path('/app/data/bank_transactions.csv')
OUTPUT_PATH = Path('/app/data/output.json')
TARGET_BASE = {'north', 'west', 'capital'}
TARGET_STRONG = TARGET_BASE | {'group', 'inc', 'incorporated', 'corp', 'company'}
NEGATIVE_TOKENS = {
    'advisor', 'advisors', 'advisory', 'partner', 'partners', 'asset', 'assets',
    'wealth', 'management', 'service', 'services', 'holdings', 'holding', 'fund', 'funds'
}
CONFUSIONS = str.maketrans({
    'O': '0', 'Q': '0', 'D': '0',
    'I': '1', 'L': '1',
    'S': '5',
    'B': '8',
    'Z': '2',
})


def tokenize_name(value: str) -> list[str]:
    cleaned = value.lower().replace('&', ' and ')
    raw = re.findall(r'[a-z0-9]+', cleaned)
    tokens: list[str] = []
    for token in raw:
        if len(token) == 1 and token.isalpha():
            continue
        if token in {'nw', 'nwc', 'nwcg'}:
            tokens.extend(['north', 'west', 'capital'])
            if token == 'nwcg':
                tokens.append('group')
            continue
        if token == 'gp':
            tokens.append('group')
            continue
        if token.startswith('northwest'):
            tokens.extend(['north', 'west'])
            suffix = token[len('northwest'):]
            if suffix:
                raw.append(suffix)
            continue
        if token.startswith('northwestcapital'):
            tokens.extend(['north', 'west', 'capital'])
            suffix = token[len('northwestcapital'):]
            if suffix:
                raw.append(suffix)
            continue
        if token.startswith('cap'):
            tokens.append('capital')
            continue
        if token.startswith('incorp'):
            tokens.append('incorporated')
            continue
        if token in {'inc', 'incorporated', 'group', 'capital', 'north', 'west'}:
            tokens.append(token)
            continue
        if token.rstrip('.'):
            tokens.append(token.rstrip('.'))
    return tokens


def normalize_account(value: str) -> str:
    compact = re.sub(r'[^A-Z0-9]', '', value.upper())
    return compact.translate(CONFUSIONS)


def name_features(value: str) -> tuple[set[str], int, bool, str]:
    normalized_text = re.sub(r'[^a-z0-9]', '', value.lower())
    tokens = set(tokenize_name(value))
    if 'northwest' in normalized_text:
        tokens.update({'north', 'west'})
    if 'northwestcapital' in normalized_text:
        tokens.update({'north', 'west', 'capital'})
    base_hits = len(tokens & TARGET_BASE)
    has_negative = bool(tokens & NEGATIVE_TOKENS)
    return tokens, base_hits, has_negative or ('advisor' in normalized_text), normalized_text


def is_anchor_name(value: str) -> bool:
    tokens, base_hits, has_negative, normalized_text = name_features(value)
    if base_hits < 3 or has_negative:
        return False
    if 'group' in tokens or 'incorporated' in tokens or 'inc' in tokens:
        return True
    return 'northwestcapital' in normalized_text


def supports_target_name(value: str) -> bool:
    tokens, base_hits, has_negative, normalized_text = name_features(value)
    if base_hits < 2 or has_negative:
        return False
    if base_hits == 3:
        return True
    return bool(tokens & {'group', 'inc', 'incorporated'}) or 'northwestcapital' in normalized_text


with INPUT_PATH.open('r', encoding='utf-8', newline='') as handle:
    rows = list(csv.DictReader(handle))

account_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
anchor_keys: set[str] = set()

for row in rows:
    key = normalize_account(row['Account Number'])
    account_rows[key].append(row)
    if is_anchor_name(row['Company Name']):
        anchor_keys.add(key)

trusted_keys = set(anchor_keys)
changed = True
while changed:
    changed = False
    for key, key_rows in account_rows.items():
        if key in trusted_keys:
            continue
        support = sum(1 for row in key_rows if supports_target_name(row['Company Name']))
        conflict = sum(1 for row in key_rows if name_features(row['Company Name'])[2])
        if support >= 1 and conflict == 0:
            trusted_keys.add(key)
            changed = True

output_rows = []
for row in rows:
    key = normalize_account(row['Account Number'])
    tokens, base_hits, has_negative, _ = name_features(row['Company Name'])
    if key not in trusted_keys:
        continue
    if has_negative and not is_anchor_name(row['Company Name']):
        continue
    output_rows.append({
        'Company Name': str(row['Company Name']),
        'Account Number': str(row['Account Number']),
        'Date': str(row['Date']),
        'Amount': str(row['Amount']),
        'Transaction Type': str(row['Transaction Type']),
        'Description': str(row['Description']),
    })

output_rows.sort(key=lambda row: row['Date'])
OUTPUT_PATH.write_text(json.dumps(output_rows, indent=2), encoding='utf-8')
PY
