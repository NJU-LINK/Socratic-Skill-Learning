#!/bin/bash

python3 <<'PY'
import json
import re
from pathlib import Path

import pandas as pd


SOURCE_PATHS = {
    "source_a": Path("/data/source_a/users.json"),
    "source_b": Path("/data/source_b/users.csv"),
    "source_c": Path("/data/source_c/users.parquet"),
}

FIELD_ALIASES = {
    "user_id": ["user_id", "id", "account_id", "user_key", "member_id"],
    "name": ["name", "full_name", "preferred_name", "display_name", "member_name"],
    "email": ["email", "primary_email", "contact_email", "email_address"],
    "created_date": [
        "created_date",
        "registration_date",
        "signup_date",
        "created_at",
        "created_on",
        "joined",
        "joined_at",
    ],
    "status": ["status", "status_text", "enabled", "is_active", "active"],
}

STATUS_MAP = {
    True: "active",
    False: "inactive",
    "true": "active",
    "false": "inactive",
    "active": "active",
    "inactive": "inactive",
    "enabled": "active",
    "disabled": "inactive",
}

OUTPUT_COLUMNS = ["user_id", "name", "email", "created_date", "status"]
CONFLICT_FIELDS = ["name", "email", "created_date", "status"]


def read_source(source_name: str) -> pd.DataFrame:
    path = SOURCE_PATHS[source_name]
    if path.suffix == ".json":
        df = pd.read_json(path)
    elif path.suffix == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_parquet(path)
    return normalize_frame(df, source_name)


def normalize_frame(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    standardized = pd.DataFrame()
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in df.columns:
                standardized[canonical] = df[alias]
                break

    if "user_id" not in standardized.columns:
        raise ValueError(f"{source_name} is missing a user id column")

    for column in OUTPUT_COLUMNS:
        if column not in standardized.columns:
            standardized[column] = pd.NA

    standardized["user_id"] = standardized["user_id"].astype("Int64")
    standardized["created_date"] = normalize_dates(standardized["created_date"], source_name)
    standardized["status"] = normalize_status(standardized["status"])

    for column in ["name", "email", "created_date", "status"]:
        standardized[column] = normalize_strings(standardized[column])

    standardized["_source"] = source_name
    return standardized[OUTPUT_COLUMNS + ["_source"]]


def normalize_dates(series: pd.Series, source_name: str) -> pd.Series:
    def convert(value):
        if pd.isna(value):
            return pd.NA
        text = str(value).strip()
        if not text:
            return pd.NA

        if source_name == "source_a":
            parsed = pd.to_datetime(text, errors="coerce", format="%Y/%m/%d")
        elif source_name == "source_b":
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", text):
                parsed = pd.to_datetime(text, errors="coerce", format="%Y-%m-%dT%H:%M:%S")
            elif re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
                parsed = pd.to_datetime(text, errors="coerce", format="%m/%d/%Y")
            else:
                parsed = pd.to_datetime(text, errors="coerce")
        elif source_name == "source_c":
            if re.fullmatch(r"\d{2}-\d{2}-\d{4}", text):
                parsed = pd.to_datetime(text, errors="coerce", format="%d-%m-%Y")
            elif re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", text):
                parsed = pd.to_datetime(text, errors="coerce", format="%Y.%m.%d")
            else:
                parsed = pd.to_datetime(text, errors="coerce")
        else:
            parsed = pd.to_datetime(text, errors="coerce")

        if pd.isna(parsed):
            return pd.NA
        return parsed.strftime("%Y-%m-%d")

    return series.map(convert)


def normalize_status(series: pd.Series) -> pd.Series:
    def convert(value):
        if pd.isna(value):
            return pd.NA
        mapped = STATUS_MAP.get(value)
        if mapped is not None:
            return mapped
        mapped = STATUS_MAP.get(str(value).strip().lower())
        return mapped if mapped is not None else str(value).strip().lower()

    return series.map(convert)


def normalize_strings(series: pd.Series) -> pd.Series:
    def convert(value):
        if pd.isna(value):
            return pd.NA
        text = str(value).strip()
        return text if text else pd.NA

    return series.map(convert)


def first_present(group: pd.DataFrame, field: str):
    for _, row in group.iterrows():
        value = row[field]
        if pd.notna(value):
            return value
    return pd.NA


def record_conflicts(group: pd.DataFrame):
    conflicts = []
    ordered = group.copy()
    source_lookup = {row["_source"]: row for _, row in ordered.iterrows()}
    for field in CONFLICT_FIELDS:
        values = {}
        distinct = []
        for source_name in ["source_a", "source_b", "source_c"]:
            if source_name not in source_lookup:
                continue
            value = source_lookup[source_name][field]
            if pd.isna(value):
                continue
            values[source_name] = value
            if value not in distinct:
                distinct.append(value)
        if len(distinct) > 1:
            conflicts.append(
                {
                    "user_id": int(ordered.iloc[0]["user_id"]),
                    "field": field,
                    "values": values,
                    "selected": first_present(ordered, field),
                }
            )
    return conflicts


def main():
    source_order = ["source_a", "source_b", "source_c"]
    frames = [read_source(source_name) for source_name in source_order]
    combined = pd.concat(frames, ignore_index=True)
    combined["_source"] = pd.Categorical(combined["_source"], categories=source_order, ordered=True)
    combined = combined.sort_values(["user_id", "_source"], kind="stable")

    merged_rows = []
    conflicts = []
    for user_id, group in combined.groupby("user_id", sort=True):
        merged_row = {"user_id": int(user_id)}
        for field in ["name", "email", "created_date", "status"]:
            value = first_present(group, field)
            merged_row[field] = None if pd.isna(value) else value
        merged_rows.append(merged_row)
        conflicts.extend(record_conflicts(group))

    merged = pd.DataFrame(merged_rows, columns=OUTPUT_COLUMNS)
    merged.to_parquet("/app/merged_users.parquet", index=False)

    report = {"total_conflicts": len(conflicts), "conflicts": conflicts}
    with open("/app/conflicts.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)


if __name__ == "__main__":
    main()
PY
