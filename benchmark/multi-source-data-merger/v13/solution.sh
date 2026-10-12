#!/bin/bash

python3 <<'PY'
import json
import os
from datetime import datetime

import pandas as pd


CANONICAL_COLUMNS = ["user_id", "name", "email", "created_date", "status"]
SOURCE_ORDER = ["source_a", "source_b", "source_c"]
DATA_ROOT = os.environ.get("DATA_ROOT", "/data")
APP_ROOT = os.environ.get("APP_ROOT", "/app")


def normalize_scalar(value):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def normalize_date(value):
    value = normalize_scalar(value)
    if value is None:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m-%d-%Y", "%m/%d/%Y", "%Y.%m.%d", "%d %b %Y"):
        try:
            return datetime.strptime(str(value), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Unsupported date format: {value!r}")
    return parsed.strftime("%Y-%m-%d")


def normalize_status(value):
    value = normalize_scalar(value)
    if value is None:
        return None

    if isinstance(value, bool):
        return "active" if value else "inactive"

    lowered = str(value).strip().lower()
    mapping = {
        "active": "active",
        "inactive": "inactive",
        "true": "active",
        "false": "inactive",
        "1": "active",
        "0": "inactive",
        "yes": "active",
        "no": "inactive",
    }
    if lowered not in mapping:
        raise ValueError(f"Unsupported status value: {value!r}")
    return mapping[lowered]


def normalize_text(value):
    value = normalize_scalar(value)
    return None if value is None else str(value)


def normalize_frame(df, rename_map, source_name):
    df = df.rename(columns=rename_map).copy()
    for column in CANONICAL_COLUMNS:
        if column not in df.columns:
            df[column] = None

    df = df[CANONICAL_COLUMNS]
    df["user_id"] = df["user_id"].apply(lambda value: None if pd.isna(value) else int(value))
    df["name"] = df["name"].apply(normalize_text)
    df["email"] = df["email"].apply(normalize_text)
    df["created_date"] = df["created_date"].apply(normalize_date)
    df["status"] = df["status"].apply(normalize_status)
    df["_source"] = source_name
    return df


def build_conflict(user_id, field, per_source_values, selected):
    ordered_values = {
        source: per_source_values[source]
        for source in SOURCE_ORDER
        if source in per_source_values
    }
    return {
        "user_id": int(user_id),
        "field": field,
        "values": ordered_values,
        "selected": selected,
    }


def main():
    with open(f"{DATA_ROOT}/source_a/users.json", "r", encoding="utf-8") as handle:
        source_a = pd.DataFrame(json.load(handle))

    source_b = pd.read_csv(f"{DATA_ROOT}/source_b/users.csv")
    source_c = pd.read_parquet(f"{DATA_ROOT}/source_c/users.parquet")

    normalized_sources = {
        "source_a": normalize_frame(
            source_a,
            {"id": "user_id", "full_name": "name", "registration_date": "created_date"},
            "source_a",
        ),
        "source_b": normalize_frame(
            source_b,
            {"email_address": "email", "created_at": "created_date", "is_active": "status"},
            "source_b",
        ),
        "source_c": normalize_frame(
            source_c,
            {"userId": "user_id", "userName": "name", "contact": "email", "joined": "created_date", "active": "status"},
            "source_c",
        ),
    }

    all_rows = pd.concat(normalized_sources.values(), ignore_index=True)
    user_ids = sorted(all_rows["user_id"].dropna().unique())

    merged_rows = []
    conflicts = []
    for user_id in user_ids:
        user_rows = {
            source: frame[frame["user_id"] == user_id].iloc[0]
            for source, frame in normalized_sources.items()
            if user_id in set(frame["user_id"].tolist())
        }

        merged_row = {"user_id": int(user_id)}
        for field in CANONICAL_COLUMNS[1:]:
            per_source_values = {}
            for source in SOURCE_ORDER:
                row = user_rows.get(source)
                if row is None:
                    continue
                value = row[field]
                if pd.isna(value) or value is None:
                    continue
                per_source_values[source] = value

            selected = None
            for source in SOURCE_ORDER:
                if source in per_source_values:
                    selected = per_source_values[source]
                    break

            if len(set(per_source_values.values())) > 1:
                conflicts.append(build_conflict(user_id, field, per_source_values, selected))

            merged_row[field] = selected

        merged_rows.append(merged_row)

    merged_df = pd.DataFrame(merged_rows, columns=CANONICAL_COLUMNS)
    merged_df.to_parquet(f"{APP_ROOT}/merged_users.parquet", index=False)

    with open(f"{APP_ROOT}/conflicts.json", "w", encoding="utf-8") as handle:
        json.dump({"total_conflicts": len(conflicts), "conflicts": conflicts}, handle, indent=2)


if __name__ == "__main__":
    main()
PY
