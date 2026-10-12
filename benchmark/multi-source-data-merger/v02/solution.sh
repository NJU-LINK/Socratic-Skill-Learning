#!/bin/bash

python3 <<'PY'
import json
from pathlib import Path

import pandas as pd


SOURCE_PRIORITY = ["source_a", "source_b", "source_c"]
OUTPUT_COLUMNS = ["user_id", "name", "email", "created_date", "status"]


def normalize_scalar(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def normalize_date(value):
    value = normalize_scalar(value)
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def normalize_status(value):
    value = normalize_scalar(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return "active" if value else "inactive"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return "active"
        if value == 0:
            return "inactive"

    lowered = str(value).strip().lower()
    if lowered in {"active", "enabled", "true", "1", "yes", "y"}:
        return "active"
    if lowered in {"inactive", "disabled", "false", "0", "no", "n"}:
        return "inactive"
    return lowered or None


def first_series(frame, candidates):
    for candidate in candidates:
        if candidate in frame.columns:
            return frame[candidate]
    return pd.Series([None] * len(frame), index=frame.index, dtype="object")


def standardize(frame, source_name, schema):
    standardized = pd.DataFrame(index=frame.index)
    standardized["user_id"] = pd.to_numeric(first_series(frame, schema["user_id"]), errors="coerce").astype("Int64")
    standardized["name"] = first_series(frame, schema["name"]).map(normalize_scalar)
    standardized["email"] = first_series(frame, schema["email"]).map(normalize_scalar)
    standardized["created_date"] = first_series(frame, schema["created_date"]).map(normalize_date)
    standardized["status"] = first_series(frame, schema["status"]).map(normalize_status)
    standardized["_source"] = source_name
    return standardized[standardized["user_id"].notna()].copy()


def select_value(user_records, field):
    for source_name in SOURCE_PRIORITY:
        source_rows = user_records[user_records["_source"] == source_name]
        if source_rows.empty:
            continue
        value = source_rows.iloc[0][field]
        if value is not None and pd.notna(value):
            return value
    return None


def main():
    source_a = pd.DataFrame(json.loads(Path("/data/source_a/users.json").read_text(encoding="utf-8")))
    source_b = pd.read_csv("/data/source_b/users.csv")
    source_c = pd.read_parquet("/data/source_c/users.parquet")

    schemas = {
        "source_a": {
            "user_id": ["id", "user_id"],
            "name": ["full_name", "name"],
            "email": ["email", "email_address", "primary_contact"],
            "created_date": ["registration_date", "created_date", "created_at", "joined"],
            "status": ["status", "account_state", "is_active", "active", "active_flag"],
        },
        "source_b": {
            "user_id": ["user_id", "id", "userId"],
            "name": ["name", "full_name", "userName"],
            "email": ["email_address", "email", "primary_contact"],
            "created_date": ["created_at", "created_date", "registration_date", "joined"],
            "status": ["account_state", "is_active", "status", "active", "active_flag"],
        },
        "source_c": {
            "user_id": ["userRef", "userId", "user_id", "id"],
            "name": ["userName", "name", "full_name"],
            "email": ["primary_contact", "email", "email_address"],
            "created_date": ["joined", "created_date", "created_at", "registration_date"],
            "status": ["active_flag", "active", "status", "account_state", "is_active"],
        },
    }

    standardized = pd.concat(
        [
            standardize(source_a, "source_a", schemas["source_a"]),
            standardize(source_b, "source_b", schemas["source_b"]),
            standardize(source_c, "source_c", schemas["source_c"]),
        ],
        ignore_index=True,
    )

    merged_rows = []
    conflicts = []
    for user_id in sorted(standardized["user_id"].astype(int).unique()):
        user_records = standardized[standardized["user_id"] == user_id]
        merged_row = {"user_id": int(user_id)}

        for field in OUTPUT_COLUMNS[1:]:
            values = {}
            for source_name in SOURCE_PRIORITY:
                source_rows = user_records[user_records["_source"] == source_name]
                if source_rows.empty:
                    continue
                value = source_rows.iloc[0][field]
                if value is not None and pd.notna(value):
                    values[source_name] = value

            selected = select_value(user_records, field)
            merged_row[field] = selected

            if len(set(values.values())) > 1:
                conflicts.append(
                    {
                        "user_id": int(user_id),
                        "field": field,
                        "values": values,
                        "selected": selected,
                    }
                )

        merged_rows.append(merged_row)

    merged = pd.DataFrame(merged_rows, columns=OUTPUT_COLUMNS)
    merged["user_id"] = merged["user_id"].astype("int64")
    merged.to_parquet("/app/merged_users.parquet", index=False)
    Path("/app/conflicts.json").write_text(
        json.dumps({"total_conflicts": len(conflicts), "conflicts": conflicts}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
PY
