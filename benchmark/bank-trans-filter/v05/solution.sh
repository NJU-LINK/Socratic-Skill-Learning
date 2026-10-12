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
LEGAL_SUFFIXES = {
    'co',
    'company',
    'corp',
    'corporation',
    'inc',
    'incorporated',
    'limited',
    'ltd',
    'llc',
    'plc',
    'pty',
}


def tokenize_name(name: str) -> list[str]:
    lowered = name.lower().replace('&', ' and ')
    return [token for token in re.findall(r'[a-z0-9]+', lowered) if token]


def edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def token_matches(token: str, canonical: str) -> bool:
    if token == canonical:
        return True
    if len(token) <= 2 or len(canonical) <= 2:
        return False
    threshold = 1 if len(canonical) <= 6 else 2
    return edit_distance(token, canonical) <= threshold


def normalize_account(account_number: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', account_number.upper())


def account_matches(left: str, right: str) -> bool:
    return edit_distance(normalize_account(left), normalize_account(right)) <= 1


def name_features(name: str) -> dict[str, int | bool]:
    features = {
        'north': False,
        'west': False,
        'capital': False,
        'group': False,
        'logistics': False,
        'nwcg': False,
        'unknown_count': 0,
    }
    significant_tokens = []

    for token in tokenize_name(name):
        if token == 'nw':
            features['north'] = True
            features['west'] = True
            significant_tokens.append(token)
            continue
        if token == 'nwcg':
            features['north'] = True
            features['west'] = True
            features['capital'] = True
            features['group'] = True
            features['nwcg'] = True
            significant_tokens.append(token)
            continue
        if token == 'northwest':
            features['north'] = True
            features['west'] = True
            significant_tokens.append(token)
            continue
        if token in LEGAL_SUFFIXES:
            continue

        significant_tokens.append(token)
        matched_target_signal = False
        if token_matches(token, 'north'):
            features['north'] = True
            matched_target_signal = True
        if token_matches(token, 'west'):
            features['west'] = True
            matched_target_signal = True
        if token_matches(token, 'capital'):
            features['capital'] = True
            matched_target_signal = True
        if token in {'grp'} or token_matches(token, 'group'):
            features['group'] = True
            matched_target_signal = True
        if token_matches(token, 'logistics'):
            features['logistics'] = True
            matched_target_signal = True
        if not matched_target_signal:
            features['unknown_count'] += 1

    initials = ''.join(token[0] for token in significant_tokens if token)
    if 'nwcg' in initials:
        features['north'] = True
        features['west'] = True
        features['capital'] = True
        features['group'] = True
        features['nwcg'] = True

    return features


def directional_count(features: dict[str, int | bool]) -> int:
    return int(bool(features['north'])) + int(bool(features['west']))


def is_strong_target_name(name: str) -> bool:
    features = name_features(name)
    return (
        not bool(features['logistics'])
        and bool(features['capital'])
        and int(features['unknown_count']) == 0
        and (
            directional_count(features) >= 2
            or (bool(features['group']) and directional_count(features) >= 1)
            or bool(features['nwcg'])
        )
    )


def has_target_name_hint(name: str) -> bool:
    features = name_features(name)
    return (
        not bool(features['logistics'])
        and bool(features['capital'])
        and int(features['unknown_count']) == 0
        and directional_count(features) >= 1
    )


def is_conflicting_name(name: str) -> bool:
    features = name_features(name)
    return bool(features['logistics']) and bool(features['capital']) and not bool(features['group'])


def account_matches_any(account_number: str, known_accounts: set[str]) -> bool:
    return any(account_matches(account_number, candidate) for candidate in known_accounts)


with INPUT_PATH.open(newline='') as handle:
    rows = list(csv.DictReader(handle))

target_accounts = {
    row['Account Number']
    for row in rows
    if is_strong_target_name(row['Company Name'])
}

changed = True
while changed:
    changed = False
    for row in rows:
        account_number = row['Account Number']
        if account_number in target_accounts or is_conflicting_name(row['Company Name']):
            continue
        if has_target_name_hint(row['Company Name']) and account_matches_any(account_number, target_accounts):
            target_accounts.add(account_number)
            changed = True

matching_rows = [
    {key: row[key] for key in FIELDNAMES}
    for row in rows
    if is_strong_target_name(row['Company Name'])
    or (
        has_target_name_hint(row['Company Name'])
        and account_matches_any(row['Account Number'], target_accounts)
        and not is_conflicting_name(row['Company Name'])
    )
    or (
        row['Account Number'] in target_accounts
        and not is_conflicting_name(row['Company Name'])
    )
]

matching_rows.sort(key=lambda row: row['Date'])

OUTPUT_PATH.write_text(json.dumps(matching_rows, indent=2) + '\n')
PY
