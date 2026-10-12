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
NOISY_TARGET_NAMES = {
    'Nrth Wst Cptl Grp',
    'NWC Grop Inc',
    'North Wst Cap',
    'Nrth West Cap Grp',
    'N W Capital Gp',
    'Nrth Wst Cptl',
    'N Wst Cap Grp',
    'NWC Group Incorporated',
}
DISTRACTOR_NAMES = {
    'North West Capital Advisory',
    'Northwestern Capital Group',
    'Northwest Capital Holding',
}


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


def is_target_anchor_name(name: str) -> bool:
    compact = re.sub(r'[^a-z0-9]+', '', name.lower())
    if any(pattern in compact for pattern in ('advis', 'hold', 'northwestern')):
        return False
    return {'north', 'west', 'capital'}.issubset(set(normalized_tokens(name)))


def load_csv_rows():
    with INPUT_PATH.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def load_output_rows():
    return json.loads(OUTPUT_PATH.read_text(encoding='utf-8'))


def expected_rows():
    anchor_accounts = {
        row['Account Number']
        for row in load_csv_rows()
        if is_target_anchor_name(row['Company Name'])
    }
    rows = [row for row in load_csv_rows() if row['Account Number'] in anchor_accounts]
    rows.sort(key=lambda row: row['Date'])
    return [{key: row[key] for key in EXPECTED_KEYS} for row in rows]


def test_output_matches_all_target_account_rows():
    assert load_output_rows() == expected_rows()


def test_output_structure_and_string_values():
    output_rows = load_output_rows()

    assert isinstance(output_rows, list)
    assert output_rows

    for row in output_rows:
        assert list(row.keys()) == EXPECTED_KEYS
        assert all(isinstance(value, str) for value in row.values())


def test_output_is_sorted_and_excludes_near_name_distractors():
    output_rows = load_output_rows()
    dates = [row['Date'] for row in output_rows]
    output_names = {row['Company Name'] for row in output_rows}

    assert dates == sorted(dates)
    assert output_names.isdisjoint(DISTRACTOR_NAMES)
    assert not any('Advisory' in row['Company Name'] for row in output_rows)
    assert not any('Northwestern' in row['Company Name'] for row in output_rows)
    assert not any('Holding' in row['Company Name'] for row in output_rows)


def test_output_includes_noisy_variants_not_just_exact_name_matches():
    output_rows = load_output_rows()
    output_names = {row['Company Name'] for row in output_rows}
    exact_name_rows = [row for row in output_rows if row['Company Name'] == 'North West Capital']

    assert len(exact_name_rows) == 2
    assert NOISY_TARGET_NAMES.issubset(output_names)
    assert len(output_rows) > len(exact_name_rows)


def test_expected_target_accounts_are_discovered_from_real_csv_rows():
    anchor_accounts = {
        row['Account Number']
        for row in load_csv_rows()
        if is_target_anchor_name(row['Company Name'])
    }

    assert anchor_accounts
    assert all(
        row['Account Number'] in anchor_accounts
        for row in load_output_rows()
    )
