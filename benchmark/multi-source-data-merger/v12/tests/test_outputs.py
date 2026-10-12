#!/usr/bin/env python3

import json
import re
from pathlib import Path

import pandas as pd


MERGED = Path("/app/merged_users.parquet")
CONFLICTS = Path("/app/conflicts.json")


def load_outputs():
    frame = pd.read_parquet(MERGED).sort_values("user_id").reset_index(drop=True)
    report = json.loads(CONFLICTS.read_text(encoding="utf-8"))
    return frame, report


def rows_by_id(frame):
    return {row.user_id: row for row in frame.itertuples(index=False)}


def conflicts_by_key(report):
    return {(item["user_id"], item["field"]): item for item in report["conflicts"]}


def test_required_outputs_exist():
    assert MERGED.is_file()
    assert CONFLICTS.is_file()


def test_parquet_schema_and_user_coverage():
    frame, _ = load_outputs()
    assert list(frame.columns) == ["user_id", "name", "email", "created_date", "status"]
    assert frame["user_id"].is_unique
    assert list(frame["user_id"]) == [201, 202, 203, 204, 205]


def test_field_level_priority_and_backfill():
    frame, _ = load_outputs()
    rows = rows_by_id(frame)

    assert (rows[201].name, rows[201].email, rows[201].created_date, rows[201].status) == (
        "Lena Ortiz", "lena@source-a.test", "2024-01-12", "active",
    )
    assert (rows[202].name, rows[202].email, rows[202].created_date, rows[202].status) == (
        "Mason Lee", "mason@source-a.test", "2024-02-05", "inactive",
    )
    assert (rows[203].name, rows[203].email, rows[203].created_date, rows[203].status) == (
        "Priya Shah", "priya@source-a.test", "2024-03-09", "active",
    )
    assert (rows[204].name, rows[204].email, rows[204].created_date, rows[204].status) == (
        "Owen Kim", "owen@source-b.test", "2024-04-18", "inactive",
    )
    assert rows[205].name == "Nia Patel"
    assert rows[205].email == "nia@source-c.test"
    assert rows[205].created_date == "2024-05-02"
    assert pd.isna(rows[205].status)


def test_dates_and_statuses_are_normalized():
    frame, _ = load_outputs()
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in frame["created_date"])
    assert set(frame["status"].dropna()) == {"active", "inactive"}


def test_conflict_report_shape_and_count():
    _, report = load_outputs()
    assert set(report) == {"total_conflicts", "conflicts"}
    assert report["total_conflicts"] == len(report["conflicts"]) == 3
    assert all(set(item) == {"user_id", "field", "values", "selected"} for item in report["conflicts"])


def test_conflicts_follow_priority_with_normalized_values():
    _, report = load_outputs()
    conflicts = conflicts_by_key(report)
    assert set(conflicts) == {(201, "email"), (202, "created_date"), (203, "email")}

    assert conflicts[(201, "email")] == {
        "user_id": 201,
        "field": "email",
        "values": {
            "source_a": "lena@source-a.test",
            "source_b": "lena@source-b.test",
            "source_c": "lena@source-c.test",
        },
        "selected": "lena@source-a.test",
    }
    assert conflicts[(202, "created_date")] == {
        "user_id": 202,
        "field": "created_date",
        "values": {
            "source_a": "2024-02-05",
            "source_c": "2024-02-09",
        },
        "selected": "2024-02-05",
    }
    assert conflicts[(203, "email")] == {
        "user_id": 203,
        "field": "email",
        "values": {
            "source_a": "priya@source-a.test",
            "source_b": "priya.alt@source-b.test",
        },
        "selected": "priya@source-a.test",
    }


def test_equivalent_statuses_and_missing_values_are_not_conflicts():
    _, report = load_outputs()
    assert all(item["field"] != "status" for item in report["conflicts"])
