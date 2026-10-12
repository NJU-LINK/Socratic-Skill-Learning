#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR

python3 - <<'PY'
import csv
import json
import os
from pathlib import Path


def add_candidate(candidates: list[tuple[Path, Path]], seen: set[Path], input_path: Path, output_path: Path) -> None:
    if input_path in seen:
        return
    seen.add(input_path)
    candidates.append((input_path, output_path))


def resolve_paths() -> tuple[Path, Path]:
    app_dir = Path(os.environ.get('APP_DIR', '/app'))
    script_dir = Path(os.environ['SCRIPT_DIR'])
    candidates = []
    seen = set()

    for base_dir in (app_dir, script_dir, script_dir.parent):
        add_candidate(candidates, seen, base_dir / 'data' / 'bank_transactions.csv', base_dir / 'data' / 'output.json')

    # In review bundles, prefer the paired Builder01 artifact over sibling seed-task dirs.
    review_root = script_dir.parent
    if review_root.exists():
        preferred_patterns = (
            'build01*_output/data/bank_transactions.csv',
            '*build01*_output/data/bank_transactions.csv',
        )
        for pattern in preferred_patterns:
            for match in sorted(review_root.glob(pattern)):
                add_candidate(candidates, seen, match, match.parent / 'output.json')

        fallback_patterns = (
            '*_output/data/bank_transactions.csv',
            '*/data/bank_transactions.csv',
        )
        for pattern in fallback_patterns:
            for match in sorted(review_root.glob(pattern)):
                add_candidate(candidates, seen, match, match.parent / 'output.json')

    parent_root = script_dir.parent.parent
    if parent_root.exists():
        for match in sorted(parent_root.glob('*/data/bank_transactions.csv')):
            add_candidate(candidates, seen, match, match.parent / 'output.json')

    for input_path, output_path in candidates:
        if input_path.exists():
            return input_path, output_path
    raise FileNotFoundError('Could not locate bank_transactions.csv from /app or review input context directories')


INPUT, OUTPUT = resolve_paths()

ROLE_TOKENS = {
    'service',
    'services',
    'shared',
    'holding',
    'holdings',
    'hldgs',
    'subsidiary',
    'sub',
    'treasury',
    'ops',
    'operations',
}


def normalize(text: str) -> str:
    return ''.join(ch.lower() if ch.isalnum() else ' ' for ch in text)


def name_signals(name: str) -> dict[str, bool | int]:
    normalized = normalize(name)
    tokens = [token for token in normalized.split() if token]
    squashed = ''.join(tokens)

    has_north_marker = 'northwest' in squashed or 'north' in tokens or 'west' in tokens or squashed.startswith('nw')
    has_capital_marker = 'capital' in tokens or 'capitel' in tokens
    has_group_marker = 'group' in tokens or 'grp' in tokens or 'gp' in tokens
    has_inc_marker = any(token.startswith('inc') for token in tokens)
    has_acronym = 'nwcg' in squashed
    has_nw_pair = any(pair in squashed for pair in ('nwest', 'northwest', 'nwcapital')) or ('n' in tokens and 'w' in tokens)
    has_role_marker = any(token in ROLE_TOKENS for token in tokens)
    positive_signals = sum((has_north_marker, has_capital_marker, has_group_marker, has_inc_marker)) + (2 if has_acronym else 0)

    return {
        'target_like': (has_north_marker and has_capital_marker and has_group_marker and has_inc_marker) or (has_acronym and has_inc_marker),
        'account_supported': (has_capital_marker and has_group_marker and (has_north_marker or has_nw_pair or has_acronym)) or (has_acronym and has_inc_marker),
        'has_role_marker': has_role_marker,
        'positive_signals': positive_signals,
    }


with INPUT.open(newline='') as fh:
    rows = list(csv.DictReader(fh))

signals_by_index = [name_signals(row['Company Name']) for row in rows]

target_accounts = {
    row['Account Number']
    for row, signals in zip(rows, signals_by_index)
    if signals['target_like'] and not signals['has_role_marker']
}

filtered = []
for row, signals in zip(rows, signals_by_index):
    if signals['has_role_marker']:
        continue
    if signals['target_like']:
        filtered.append(row)
        continue
    if row['Account Number'] in target_accounts and signals['account_supported'] and signals['positive_signals'] >= 3:
        filtered.append(row)

filtered.sort(key=lambda row: row['Date'])

OUTPUT.write_text(json.dumps(filtered, indent=2))
PY
