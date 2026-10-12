#!/bin/bash

python3 <<'PY'
import json
from pathlib import Path

import pandas as pd


OUTPUT_PARQUET = Path('/app/merged_users.parquet')
OUTPUT_CONFLICTS = Path('/app/conflicts.json')
FIELDS = ['name', 'email', 'created_date', 'status']
SOURCE_ORDER = ['source_a', 'source_b', 'source_c']


def normalize_date(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors='raise', format='mixed')
    return parsed.dt.strftime('%Y-%m-%d')


def normalize_source_a() -> pd.DataFrame:
    with open('/data/source_a/users.json', 'r', encoding='utf-8') as handle:
        rows = json.load(handle)
    frame = pd.DataFrame(rows).rename(
        columns={
            'id': 'user_id',
            'full_name': 'name',
            'registration_date': 'created_date',
        }
    )
    frame['created_date'] = normalize_date(frame['created_date'])
    frame['_source'] = 'source_a'
    return frame[['user_id', 'name', 'email', 'created_date', 'status', '_source']]


def normalize_source_b() -> pd.DataFrame:
    frame = pd.read_csv('/data/source_b/users.csv').rename(
        columns={
            'email_address': 'email',
            'created_at': 'created_date',
        }
    )
    frame['created_date'] = normalize_date(frame['created_date'])
    frame['status'] = frame['is_active'].map({True: 'active', False: 'inactive'})
    frame['_source'] = 'source_b'
    return frame[['user_id', 'name', 'email', 'created_date', 'status', '_source']]


def normalize_source_c() -> pd.DataFrame:
    frame = pd.read_parquet('/data/source_c/users.parquet').rename(
        columns={
            'userId': 'user_id',
            'userName': 'name',
            'joined': 'created_date',
        }
    )
    frame['created_date'] = normalize_date(frame['created_date'])
    frame['status'] = frame['active'].map({True: 'active', False: 'inactive'})
    frame['_source'] = 'source_c'
    return frame[['user_id', 'name', 'email', 'created_date', 'status', '_source']]


def first_non_null(group: pd.DataFrame, field: str):
    for source in SOURCE_ORDER:
        rows = group[group['_source'] == source]
        if rows.empty:
            continue
        value = rows.iloc[0][field]
        if pd.notna(value):
            return value
    return None


def build_merged_row(group: pd.DataFrame) -> dict:
    merged = {'user_id': int(group.iloc[0]['user_id'])}
    for field in FIELDS:
        merged[field] = first_non_null(group, field)
    return merged


def build_conflicts(group: pd.DataFrame) -> list[dict]:
    user_id = int(group.iloc[0]['user_id'])
    conflicts = []
    for field in FIELDS:
        values = {}
        for source in SOURCE_ORDER:
            rows = group[group['_source'] == source]
            if rows.empty:
                continue
            value = rows.iloc[0][field]
            if pd.notna(value):
                values[source] = value.item() if hasattr(value, 'item') else value
        if len(set(values.values())) > 1:
            conflicts.append(
                {
                    'user_id': user_id,
                    'field': field,
                    'values': values,
                    'selected': first_non_null(group, field),
                }
            )
    return conflicts


def main() -> None:
    frames = [normalize_source_a(), normalize_source_b(), normalize_source_c()]
    all_rows = pd.concat(frames, ignore_index=True)

    merged_rows = []
    all_conflicts = []
    for user_id in sorted(all_rows['user_id'].unique()):
        group = all_rows[all_rows['user_id'] == user_id].copy()
        merged_rows.append(build_merged_row(group))
        all_conflicts.extend(build_conflicts(group))

    merged = pd.DataFrame(merged_rows, columns=['user_id', 'name', 'email', 'created_date', 'status'])
    merged.to_parquet(OUTPUT_PARQUET, index=False)

    report = {
        'total_conflicts': len(all_conflicts),
        'conflicts': all_conflicts,
    }
    OUTPUT_CONFLICTS.write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
PY
