#!/bin/bash

set -euo pipefail

python3 - <<'PY'
import json
from pathlib import Path

import pandas as pd


SOURCE_PRIORITY = ["source_a", "source_b", "source_c"]
CANONICAL_COLUMNS = ["user_id", "name", "email", "created_date", "status"]


def rename_columns(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    available = {key: value for key, value in mapping.items() if key in df.columns}
    return df.rename(columns=available)


def normalize_status(value):
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return "active" if value else "inactive"

    text = str(value).strip()
    lowered = text.lower()
    if lowered in {"true", "1", "yes", "y", "active"}:
        return "active"
    if lowered in {"false", "0", "no", "n", "inactive"}:
        return "inactive"
    return text


def parse_date(value: object) -> str:
    text = str(value).strip()
    for kwargs in (
        {"format": "%Y/%m/%d"},
        {"format": "%Y-%m-%dT%H:%M:%S"},
        {"format": "%d-%m-%Y"},
    ):
        try:
            return pd.to_datetime(text, errors="raise", **kwargs).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            continue
    return pd.to_datetime(text, errors="raise").strftime("%Y-%m-%d")


def normalize_date(series: pd.Series) -> pd.Series:
    return series.map(parse_date)


def load_source_a() -> pd.DataFrame:
    df = pd.read_json("/data/source_a/users.json")
    df = rename_columns(
        df,
        {
            "user_identifier": "user_id",
            "full_name": "name",
            "registered_on": "created_date",
        },
    )
    return df


def load_source_b() -> pd.DataFrame:
    df = pd.read_csv("/data/source_b/users.csv")
    df = rename_columns(
        df,
        {
            "mail": "email",
            "signup_ts": "created_date",
            "is_active": "status",
        },
    )
    return df


def load_source_c() -> pd.DataFrame:
    df = pd.read_parquet("/data/source_c/users.parquet")
    df = rename_columns(
        df,
        {
            "userId": "user_id",
            "member_name": "name",
            "email_address": "email",
            "joined": "created_date",
            "active": "status",
        },
    )
    return df


def prepare(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    df = df.copy()
    for column in CANONICAL_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df["user_id"] = df["user_id"].astype("int64")
    df["created_date"] = normalize_date(df["created_date"])
    df["status"] = df["status"].map(normalize_status)
    df["_source"] = source_name
    return df[["user_id", *CANONICAL_COLUMNS[1:], "_source"]]


def first_non_null(values: list[object]):
    for value in values:
        if pd.notna(value):
            return value
    return None


sources = {
    "source_a": prepare(load_source_a(), "source_a"),
    "source_b": prepare(load_source_b(), "source_b"),
    "source_c": prepare(load_source_c(), "source_c"),
}

all_users = sorted({int(user_id) for df in sources.values() for user_id in df["user_id"]})
conflicts = []
merged_rows = []

for user_id in all_users:
    per_source = {}
    for source_name, df in sources.items():
        matches = df[df["user_id"] == user_id]
        per_source[source_name] = matches.iloc[0] if not matches.empty else None

    merged_row = {"user_id": user_id}
    for field in CANONICAL_COLUMNS[1:]:
        values_by_source = {}
        ordered_values = []
        for source_name in SOURCE_PRIORITY:
            row = per_source[source_name]
            if row is None:
                continue
            value = row[field]
            if pd.notna(value):
                values_by_source[source_name] = value.item() if hasattr(value, "item") else value
            ordered_values.append(value)

        present_values = [str(value) for value in values_by_source.values() if value is not None]
        selected = first_non_null(ordered_values)
        selected = selected.item() if hasattr(selected, "item") else selected
        merged_row[field] = selected

        unique_values = {value for value in present_values}
        if len(unique_values) > 1:
            conflicts.append(
                {
                    "user_id": user_id,
                    "field": field,
                    "values": values_by_source,
                    "selected": selected,
                }
            )

    merged_rows.append(merged_row)

merged_df = pd.DataFrame(merged_rows, columns=CANONICAL_COLUMNS)
merged_df["user_id"] = merged_df["user_id"].astype("int64")
merged_df.to_parquet("/app/merged_users.parquet", index=False)

report = {"total_conflicts": len(conflicts), "conflicts": conflicts}
Path("/app/conflicts.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
PY
