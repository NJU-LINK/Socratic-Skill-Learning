import hashlib
import json
import re
from pathlib import Path

import pandas as pd


MERGED = Path("/app/merged_users.parquet")
CONFLICTS = Path("/app/conflicts.json")
INPUT_HASHES = {
    Path("/data/source_a/users.json"): "225b60211f01e73edfbc71141bc0f02490fa65f50a00a25112531e8c59b7c669",
    Path("/data/source_b/users.csv"): "1317021612a336d25293dd05a0e07c2e8dd1cc3931821ebd159800da78236aca",
    Path("/data/source_c/users.parquet"): "c0cb58f81b0432dee6bb4f5d7092593f3c1c7160e0f4d677377b744a8b827fb1",
}


def outputs():
    frame = pd.read_parquet(MERGED).sort_values("user_id").reset_index(drop=True)
    report = json.loads(CONFLICTS.read_text(encoding="utf-8"))
    return frame, report


def records(frame):
    return [
        {
            key: None if pd.isna(value) else value
            for key, value in record.items()
        }
        for record in frame.to_dict(orient="records")
    ]


def test_required_outputs_exist():
    assert MERGED.is_file()
    assert CONFLICTS.is_file()


def test_parquet_schema_and_user_coverage():
    frame, _ = outputs()
    assert list(frame.columns) == ["user_id", "name", "email", "created_date", "status"]
    assert str(frame["user_id"].dtype) == "int64"
    assert frame["user_id"].is_unique
    assert frame["user_id"].tolist() == [101, 102, 103, 104]


def test_field_level_priority_and_backfill():
    frame, _ = outputs()
    assert records(frame) == [
        {
            "user_id": 101,
            "name": "John Doe",
            "email": "john@a.com",
            "created_date": "2024-01-15",
            "status": "active",
        },
        {
            "user_id": 102,
            "name": "Jane Smith",
            "email": "jane@a.com",
            "created_date": "2024-02-20",
            "status": "inactive",
        },
        {
            "user_id": 103,
            "name": "Bob Wilson",
            "email": "bob@b.com",
            "created_date": "2024-03-01",
            "status": "active",
        },
        {
            "user_id": 104,
            "name": "Alice Brown",
            "email": "alice@c.com",
            "created_date": "2024-04-01",
            "status": "active",
        },
    ]


def test_dates_and_statuses_are_normalized():
    frame, _ = outputs()
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in frame["created_date"])
    assert set(frame["status"]) == {"active", "inactive"}


def test_conflicts_are_normalized_field_level_disagreements():
    _, report = outputs()
    assert report == {
        "total_conflicts": 1,
        "conflicts": [
            {
                "user_id": 101,
                "field": "email",
                "values": {
                    "source_a": "john@a.com",
                    "source_b": "john@b.com",
                },
                "selected": "john@a.com",
            }
        ],
    }


def test_input_sources_are_unchanged():
    for source, expected in INPUT_HASHES.items():
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
