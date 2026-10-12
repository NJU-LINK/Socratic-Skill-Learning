#!/bin/bash

set -euo pipefail

python3 - <<'PY'
import json
from pathlib import Path

import pandas as pd


SOURCE_PRIORITY = ["source_a", "source_b", "source_c"]
CANONICAL_COLUMNS = ["user_id", "name", "email", "created_date", "status"]
SOURCE_CONFIG = {
    "source_a": {
        "path": "/data/source_a/users.json",
        "loader": pd.read_json,
        "rename": {
            "acct_id": "user_id",
            "preferred_name": "name",
            "contact_email": "email",
            "registered_on": "created_date",
            "member_state": "status",
        },
    },
    "source_b": {
        "path": "/data/source_b/users.csv",
        "loader": pd.read_csv,
        "rename": {
            "user_ref": "user_id",
            "display_label": "name",
            "email_address": "email",
            "created_at": "created_date",
            "lifecycle": "status",
        },
    },
    "source_c": {
        "path": "/data/source_c/users.parquet",
        "loader": pd.read_parquet,
        "rename": {
            "userId": "user_id",
            "fullName": "name",
            "email": "email",
            "joined_on": "created_date",
            "status_flag": "status",
        },
    },
}


def to_python(value):
    if hasattr(value, "item"):
        try:
            value = value.item()
        except ValueError:
            pass
    if pd.isna(value):
        return None
    return value


def clean_text(value):
    value = to_python(value)
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def parse_date(value):
    text = clean_text(value)
    if text is None:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d-%b-%Y",
        "%B %d, %Y",
    ):
        try:
            return pd.to_datetime(text, format=fmt, errors="raise").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass

    return pd.to_datetime(text, errors="raise").strftime("%Y-%m-%d")


def normalize_status(value):
    value = to_python(value)
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return "active" if value else "inactive"

    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered in {"active", "enabled", "true", "1", "yes", "y"}:
        return "active"
    if lowered in {"inactive", "disabled", "false", "0", "no", "n"}:
        return "inactive"
    return lowered


def first_non_null(values):
    for value in values:
        if value is not None:
            return value
    return None


def collapse_source(df):
    rows = []
    for user_id, group in df.groupby("user_id", sort=True, dropna=False):
        if pd.isna(user_id):
            continue
        merged = {"user_id": int(user_id)}
        for field in CANONICAL_COLUMNS[1:]:
            values = [to_python(value) for value in group[field].tolist()]
            merged[field] = first_non_null(values)
        rows.append(merged)
    return pd.DataFrame(rows, columns=CANONICAL_COLUMNS)


def load_source(source_name):
    config = SOURCE_CONFIG[source_name]
    df = config["loader"](config["path"])
    rename_map = {key: value for key, value in config["rename"].items() if key in df.columns}
    df = df.rename(columns=rename_map).copy()

    for column in CANONICAL_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df["user_id"] = pd.to_numeric(df["user_id"], errors="coerce")
    df["name"] = df["name"].map(clean_text)
    df["email"] = df["email"].map(clean_text)
    df["created_date"] = df["created_date"].map(parse_date)
    df["status"] = df["status"].map(normalize_status)

    return collapse_source(df[[*CANONICAL_COLUMNS]])


sources = {name: load_source(name).set_index("user_id") for name in SOURCE_PRIORITY}
all_user_ids = sorted({int(user_id) for source_df in sources.values() for user_id in source_df.index.tolist()})

merged_rows = []
conflicts = []

for user_id in all_user_ids:
    merged_row = {"user_id": user_id}
    for field in CANONICAL_COLUMNS[1:]:
        values_by_source = {}
        ordered_values = []

        for source_name in SOURCE_PRIORITY:
            source_df = sources[source_name]
            if user_id not in source_df.index:
                continue
            value = to_python(source_df.at[user_id, field])
            if value is not None:
                values_by_source[source_name] = value
                ordered_values.append(value)

        selected = first_non_null(ordered_values)
        merged_row[field] = selected

        if len(set(values_by_source.values())) > 1:
            conflicts.append(
                {
                    "user_id": user_id,
                    "field": field,
                    "values": values_by_source,
                    "selected": selected,
                }
            )

    merged_rows.append(merged_row)

merged_df = pd.DataFrame(merged_rows, columns=CANONICAL_COLUMNS).sort_values("user_id").reset_index(drop=True)
merged_df["user_id"] = merged_df["user_id"].astype("int64")
merged_df.to_parquet("/app/merged_users.parquet", index=False)

report = {"total_conflicts": len(conflicts), "conflicts": conflicts}
Path("/app/conflicts.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
PY
