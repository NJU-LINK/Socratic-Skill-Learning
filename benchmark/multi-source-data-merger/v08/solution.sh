#!/bin/bash
set -euo pipefail

python3 - <<'PY'
import json
from collections import defaultdict

import pandas as pd

OUTPUT_COLUMNS = ["user_id", "name", "email", "created_date", "status"]
SOURCE_PRIORITY = ["source_a", "source_b", "source_c"]


def clean_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def normalize_date(value):
    value = clean_value(value)
    if value is None:
        return None
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def normalize_status(value):
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return "active" if value else "inactive"
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "active"}:
        return "active"
    if lowered in {"false", "0", "no", "inactive"}:
        return "inactive"
    return lowered


def load_source_a():
    df = pd.read_json("/data/source_a/users.json")
    df = df.rename(
        columns={
            "id": "user_id",
            "full_name": "name",
            "registration_date": "created_date",
        }
    )
    df["created_date"] = df["created_date"].apply(normalize_date)
    df["status"] = df["status"].apply(normalize_status)
    return df[OUTPUT_COLUMNS]


def load_source_b():
    df = pd.read_csv("/data/source_b/users.csv")
    df = df.rename(
        columns={
            "email_address": "email",
            "created_at": "created_date",
            "is_active": "status",
        }
    )
    df["created_date"] = df["created_date"].apply(normalize_date)
    df["status"] = df["status"].apply(normalize_status)
    return df[OUTPUT_COLUMNS]


def load_source_c():
    df = pd.read_parquet("/data/source_c/users.parquet")
    df = df.rename(
        columns={
            "userId": "user_id",
            "userName": "name",
            "joined": "created_date",
            "active": "status",
        }
    )
    df["created_date"] = df["created_date"].apply(normalize_date)
    df["status"] = df["status"].apply(normalize_status)
    return df[OUTPUT_COLUMNS]


sources = {
    "source_a": load_source_a(),
    "source_b": load_source_b(),
    "source_c": load_source_c(),
}

records_by_user = defaultdict(dict)
for source_name, df in sources.items():
    for row in df.to_dict(orient="records"):
        user_id = int(row["user_id"])
        normalized = {column: clean_value(row.get(column)) for column in OUTPUT_COLUMNS}
        normalized["user_id"] = user_id
        records_by_user[user_id][source_name] = normalized

merged_rows = []
conflicts = []

for user_id in sorted(records_by_user):
    source_rows = records_by_user[user_id]
    merged_row = {"user_id": user_id}

    for field in OUTPUT_COLUMNS[1:]:
        selected = None
        for source_name in SOURCE_PRIORITY:
            row = source_rows.get(source_name)
            if row is None:
                continue
            candidate = row.get(field)
            if candidate is not None:
                selected = candidate
                break
        merged_row[field] = selected

        present_values = {}
        distinct_values = set()
        for source_name in SOURCE_PRIORITY:
            row = source_rows.get(source_name)
            if row is None:
                continue
            candidate = row.get(field)
            if candidate is None:
                continue
            present_values[source_name] = candidate
            distinct_values.add(candidate)

        if len(distinct_values) > 1:
            conflicts.append(
                {
                    "user_id": user_id,
                    "field": field,
                    "values": present_values,
                    "selected": selected,
                }
            )

    merged_rows.append(merged_row)

merged_df = pd.DataFrame(merged_rows, columns=OUTPUT_COLUMNS)
merged_df.to_parquet("/app/merged_users.parquet", index=False)

with open("/app/conflicts.json", "w", encoding="utf-8") as handle:
    json.dump(
        {
            "total_conflicts": len(conflicts),
            "conflicts": conflicts,
        },
        handle,
        indent=2,
    )
PY
