#!/usr/bin/env python3

import json
import os

import pandas as pd


APP_ROOT = os.environ.get("APP_ROOT", "/app")


def test_output_files_exist():
    assert os.path.exists(f"{APP_ROOT}/merged_users.parquet")
    assert os.path.exists(f"{APP_ROOT}/conflicts.json")


def test_merged_rows_match_expected_field_level_priority():
    df = pd.read_parquet(f"{APP_ROOT}/merged_users.parquet")
    actual = df.sort_values("user_id").to_dict(orient="records")

    expected = [
        {
            "user_id": 201,
            "name": "Avery Stone",
            "email": "avery@beta.io",
            "created_date": "2024-01-05",
            "status": "active",
        },
        {
            "user_id": 202,
            "name": "Bianca Hart",
            "email": "bianca@alpha.io",
            "created_date": "2024-02-10",
            "status": "inactive",
        },
        {
            "user_id": 203,
            "name": "Caleb Ng",
            "email": "caleb@beta.io",
            "created_date": "2024-03-03",
            "status": "active",
        },
        {
            "user_id": 204,
            "name": "Darius Cole",
            "email": "darius@beta.io",
            "created_date": "2024-04-20",
            "status": "inactive",
        },
        {
            "user_id": 205,
            "name": "Elio Park",
            "email": "elio@archive.io",
            "created_date": "2024-05-30",
            "status": "active",
        },
        {
            "user_id": 206,
            "name": "Farah Noor",
            "email": "farah@beta.io",
            "created_date": "2024-06-18",
            "status": "inactive",
        },
    ]

    assert actual == expected


def test_field_level_backfill_happens_instead_of_whole_row_selection():
    df = pd.read_parquet(f"{APP_ROOT}/merged_users.parquet").set_index("user_id")

    assert df.loc[201, "email"] == "avery@beta.io"
    assert df.loc[204, "email"] == "darius@beta.io"
    assert df.loc[204, "created_date"] == "2024-04-20"
    assert df.loc[206, "email"] == "farah@beta.io"
    assert df.loc[206, "created_date"] == "2024-06-18"
    assert df.loc[206, "status"] == "inactive"


def test_conflict_report_contains_normalized_conflicts_and_selected_values():
    with open(f"{APP_ROOT}/conflicts.json", "r", encoding="utf-8") as handle:
        report = json.load(handle)

    expected_conflicts = {
        (201, "email"): {
            "values": {"source_b": "avery@beta.io", "source_c": "avery@legacy.io"},
            "selected": "avery@beta.io",
        },
        (201, "created_date"): {
            "values": {"source_a": "2024-01-05", "source_b": "2024-01-05", "source_c": "2024-01-07"},
            "selected": "2024-01-05",
        },
        (202, "email"): {
            "values": {
                "source_a": "bianca@alpha.io",
                "source_b": "bianca@beta.io",
                "source_c": "bianca@archive.io",
            },
            "selected": "bianca@alpha.io",
        },
        (202, "created_date"): {
            "values": {"source_a": "2024-02-10", "source_b": "2024-02-12", "source_c": "2024-02-10"},
            "selected": "2024-02-10",
        },
        (202, "status"): {
            "values": {"source_b": "inactive", "source_c": "active"},
            "selected": "inactive",
        },
        (204, "email"): {
            "values": {"source_b": "darius@beta.io", "source_c": "darius@archive.io"},
            "selected": "darius@beta.io",
        },
        (204, "created_date"): {
            "values": {"source_b": "2024-04-20", "source_c": "2024-04-22"},
            "selected": "2024-04-20",
        },
        (204, "status"): {
            "values": {"source_a": "inactive", "source_b": "active", "source_c": "inactive"},
            "selected": "inactive",
        },
        (206, "name"): {
            "values": {"source_a": "Farah Noor", "source_b": "Farah Noor", "source_c": "Farah N."},
            "selected": "Farah Noor",
        },
        (206, "email"): {
            "values": {"source_b": "farah@beta.io", "source_c": "farah@archive.io"},
            "selected": "farah@beta.io",
        },
        (206, "created_date"): {
            "values": {"source_a": "2024-06-18", "source_b": "2024-06-19", "source_c": "2024-06-18"},
            "selected": "2024-06-18",
        },
        (206, "status"): {
            "values": {"source_b": "inactive", "source_c": "active"},
            "selected": "inactive",
        },
    }

    actual_conflicts = {
        (entry["user_id"], entry["field"]): {
            "values": entry["values"],
            "selected": entry["selected"],
        }
        for entry in report["conflicts"]
    }

    assert report["total_conflicts"] == len(expected_conflicts)
    assert actual_conflicts == expected_conflicts
