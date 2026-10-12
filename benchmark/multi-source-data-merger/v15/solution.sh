#!/bin/bash

python3 <<'PY'
import json
from collections import defaultdict

import pandas as pd


CANONICAL_FIELDS = ["user_id", "name", "email", "created_date", "status"]
SOURCE_PRIORITY = ["source_a", "source_b", "source_c"]


def clean_scalar(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_name(value):
    text = clean_scalar(value)
    if not text:
        return None
    return " ".join(text.split()).title()


def normalize_email(value):
    text = clean_scalar(value)
    if not text:
        return None
    return text.lower()


def normalize_date(value):
    text = clean_scalar(value)
    if not text:
        return None
    return pd.to_datetime(text, utc=True).strftime("%Y-%m-%d")


def normalize_status(value):
    text = clean_scalar(value)
    if not text:
        return None
    lowered = text.lower()
    active_values = {"active", "enabled", "true", "1", "on"}
    inactive_values = {"inactive", "disabled", "off", "false", "0"}
    if lowered in active_values:
        return "active"
    if lowered in inactive_values:
        return "inactive"
    raise ValueError(f"Unrecognized status value: {value!r}")


def normalize_user_id(value):
    text = clean_scalar(value)
    if text is None:
        return None
    return int(text)


NORMALIZERS = {
    "user_id": normalize_user_id,
    "name": normalize_name,
    "email": normalize_email,
    "created_date": normalize_date,
    "status": normalize_status,
}


def load_source_a():
    with open("/data/source_a/users.json", "r", encoding="utf-8") as handle:
        records = json.load(handle)
    return pd.DataFrame(records).rename(
        columns={
            "member_ref": "user_id",
            "display_name": "name",
            "contact_email": "email",
            "signup_day": "created_date",
            "account_state": "status",
        }
    )


def load_source_b():
    return pd.read_csv("/data/source_b/users.csv").rename(
        columns={
            "person_id": "user_id",
            "legal_name": "name",
            "email_contact": "email",
            "created_ts": "created_date",
            "lifecycle": "status",
        }
    )


def load_source_c():
    return pd.read_parquet("/data/source_c/users.parquet").rename(
        columns={
            "uid": "user_id",
            "preferred_name": "name",
            "mail": "email",
            "joined_on": "created_date",
            "enabled_flag": "status",
        }
    )


def normalize_records(frame, source_name):
    records = []
    for row in frame.to_dict(orient="records"):
        normalized = {field: None for field in CANONICAL_FIELDS}
        for field in CANONICAL_FIELDS:
            normalized[field] = NORMALIZERS[field](row.get(field))
        normalized["_source"] = source_name
        records.append(normalized)
    return records


def build_outputs(records_by_user):
    merged_rows = []
    conflicts = []

    for user_id in sorted(records_by_user):
        source_rows = {row["_source"]: row for row in records_by_user[user_id]}
        merged = {"user_id": user_id}

        for field in CANONICAL_FIELDS[1:]:
            values_by_source = {}
            selected = None

            for source_name in SOURCE_PRIORITY:
                row = source_rows.get(source_name)
                if not row:
                    continue
                value = row.get(field)
                if value is None:
                    continue
                values_by_source[source_name] = value
                if selected is None:
                    selected = value

            merged[field] = selected

            if len(set(values_by_source.values())) > 1:
                conflicts.append(
                    {
                        "user_id": user_id,
                        "field": field,
                        "values": {
                            source_name: values_by_source[source_name]
                            for source_name in SOURCE_PRIORITY
                            if source_name in values_by_source
                        },
                        "selected": selected,
                    }
                )

        merged_rows.append(merged)

    merged_df = pd.DataFrame(merged_rows, columns=CANONICAL_FIELDS)
    merged_df["user_id"] = merged_df["user_id"].astype("int64")
    for field in CANONICAL_FIELDS[1:]:
        merged_df[field] = merged_df[field].astype("string")

    conflict_report = {"total_conflicts": len(conflicts), "conflicts": conflicts}
    return merged_df, conflict_report


def main():
    source_frames = {
        "source_a": load_source_a(),
        "source_b": load_source_b(),
        "source_c": load_source_c(),
    }

    records_by_user = defaultdict(list)
    for source_name in SOURCE_PRIORITY:
        for record in normalize_records(source_frames[source_name], source_name):
            records_by_user[record["user_id"]].append(record)

    merged_df, conflict_report = build_outputs(records_by_user)
    merged_df.to_parquet("/app/merged_users.parquet", index=False)

    with open("/app/conflicts.json", "w", encoding="utf-8") as handle:
        json.dump(conflict_report, handle, indent=2)


if __name__ == "__main__":
    main()
PY
