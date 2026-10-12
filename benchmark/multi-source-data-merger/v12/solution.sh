#!/bin/bash

python3 <<'PY'
import json
from pathlib import Path

import pandas as pd


OUTPUT_PARQUET = Path("/app/merged_users.parquet")
OUTPUT_CONFLICTS = Path("/app/conflicts.json")
FIELDS = ["name", "email", "created_date", "status"]


def normalize_status(value):
    if pd.isna(value):
        return pd.NA

    mapping = {
        "enabled": "active",
        "disabled": "inactive",
        "y": "active",
        "n": "inactive",
        "current": "active",
        "former": "inactive",
        "active": "active",
        "inactive": "inactive",
    }

    normalized = mapping.get(str(value).strip().lower())
    if normalized is None:
        raise ValueError(f"Unsupported status value: {value!r}")
    return normalized


def normalize_frame(frame, source_name, priority, rename_map):
    frame = frame.rename(columns=rename_map).copy()
    frame = frame[[column for column in ["user_id", "name", "email", "created_date", "status"] if column in frame.columns]]

    for column in ["name", "email", "created_date", "status"]:
        if column not in frame.columns:
            frame[column] = pd.NA

    frame["user_id"] = frame["user_id"].astype(int)
    frame["created_date"] = pd.to_datetime(frame["created_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["status"] = frame["status"].apply(normalize_status)
    frame["_source"] = source_name
    frame["_priority"] = priority
    return frame[["user_id", "name", "email", "created_date", "status", "_source", "_priority"]]


with open("/data/source_a/users.json", "r", encoding="utf-8") as handle:
    source_a = pd.DataFrame(json.load(handle))

source_b = pd.read_csv("/data/source_b/users.csv")
source_c = pd.read_parquet("/data/source_c/users.parquet")

normalized = pd.concat(
    [
        normalize_frame(
            source_a,
            "source_a",
            1,
            {
                "id": "user_id",
                "full_name": "name",
                "registration_date": "created_date",
            },
        ),
        normalize_frame(
            source_b,
            "source_b",
            2,
            {
                "email_address": "email",
                "created_at": "created_date",
                "account_flag": "status",
            },
        ),
        normalize_frame(
            source_c,
            "source_c",
            3,
            {
                "userId": "user_id",
                "userName": "name",
                "joined": "created_date",
                "member_state": "status",
            },
        ),
    ],
    ignore_index=True,
).sort_values(["user_id", "_priority"], kind="stable")

merged_rows = []
conflicts = []

for user_id, group in normalized.groupby("user_id", sort=True):
    group = group.sort_values("_priority", kind="stable")
    merged_row = {"user_id": int(user_id)}

    for field in FIELDS:
        available = group.loc[group[field].notna(), ["_source", field]]
        selected = available.iloc[0][field] if not available.empty else pd.NA
        merged_row[field] = selected

        unique_values = []
        values_by_source = {}
        for _, record in available.iterrows():
            value = record[field]
            value_str = str(value)
            values_by_source[record["_source"]] = value_str
            if value_str not in unique_values:
                unique_values.append(value_str)

        if len(values_by_source) > 1 and len(unique_values) > 1:
            conflicts.append(
                {
                    "user_id": int(user_id),
                    "field": field,
                    "values": values_by_source,
                    "selected": str(selected),
                }
            )

    merged_rows.append(merged_row)

merged = pd.DataFrame(merged_rows, columns=["user_id", "name", "email", "created_date", "status"])
merged.to_parquet(OUTPUT_PARQUET, index=False)

with OUTPUT_CONFLICTS.open("w", encoding="utf-8") as handle:
    json.dump({"total_conflicts": len(conflicts), "conflicts": conflicts}, handle, indent=2)
PY
