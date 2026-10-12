"""Input-derived, output-only contract checks for the merger family."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.api.types import is_integer_dtype


SOURCE_ORDER = ("source_a", "source_b", "source_c")
OUTPUT_COLUMNS = ("user_id", "name", "email", "created_date", "status")
VALUE_FIELDS = OUTPUT_COLUMNS[1:]
DATA_ROOT = Path("/data")
MERGED_PATH = Path("/app/merged_users.parquet")
CONFLICTS_PATH = Path("/app/conflicts.json")

DEFAULT_STATUS_MAP = {
    "1": "active",
    "true": "active",
    "yes": "active",
    "y": "active",
    "on": "active",
    "active": "active",
    "enabled": "active",
    "0": "inactive",
    "false": "inactive",
    "no": "inactive",
    "n": "inactive",
    "off": "inactive",
    "inactive": "inactive",
    "disabled": "inactive",
    "paused": "suspended",
    "suspended": "suspended",
}

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%d-%b-%Y",
    "%B %d, %Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _python_scalar(value: Any) -> Any:
    if _is_missing(value):
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    return value


def _clean_text(value: Any) -> str | None:
    value = _python_scalar(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_date(value: Any, date_formats: tuple[str, ...] = DATE_FORMATS) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    for date_format in date_formats:
        try:
            return pd.to_datetime(text, format=date_format, errors="raise").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            continue
    raise AssertionError(f"Public fixture contains an unsupported date value: {text!r}")


class ContractVerifier:
    """Derive the unique expected merge from public inputs and a public schema contract."""

    def __init__(self, contract: dict[str, Any]):
        self.contract = contract
        self.name_mode = contract.get("name_mode", "strip")
        self.email_mode = contract.get("email_mode", "strip")
        self.status_map = {**DEFAULT_STATUS_MAP, **contract.get("status_map", {})}
        self.records = self._load_records()
        self.expected_frame, self.expected_conflicts = self._derive_expected()
        self.overlap_users, self.backfilled_fields = self._fixture_mechanism_counts()

    def _read_source(self, source_name: str) -> pd.DataFrame:
        if source_name == "source_a":
            payload = json.loads((DATA_ROOT / source_name / "users.json").read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                lists = [value for value in payload.values() if isinstance(value, list)]
                if len(lists) != 1:
                    raise AssertionError("JSON input must be a list or contain exactly one record list")
                payload = lists[0]
            return pd.DataFrame(payload)
        if source_name == "source_b":
            return pd.read_csv(DATA_ROOT / source_name / "users.csv")
        return pd.read_parquet(DATA_ROOT / source_name / "users.parquet")

    def _normalize(self, source_name: str, field: str, value: Any) -> Any:
        if field == "user_id":
            value = _python_scalar(value)
            if value is None:
                return None
            numeric = float(value)
            if not numeric.is_integer():
                raise AssertionError(f"user_id must be integral, got {value!r}")
            return int(numeric)
        if field == "created_date":
            date_formats = tuple(self.contract.get("date_formats", {}).get(source_name, DATE_FORMATS))
            return _normalize_date(value, date_formats)
        if field == "status":
            text = _clean_text(value)
            if text is None:
                return None
            key = text.casefold()
            if key not in self.status_map:
                raise AssertionError(f"Public fixture contains an undocumented status: {text!r}")
            return self.status_map[key]
        text = _clean_text(value)
        if text is None:
            return None
        if field == "name" and self.name_mode == "title":
            return " ".join(text.split()).title()
        if field == "email" and self.email_mode == "lower":
            return text.casefold()
        return text

    def _load_records(self) -> dict[int, dict[str, dict[str, Any]]]:
        records: dict[int, dict[str, dict[str, Any]]] = {}
        mappings = self.contract["mappings"]
        for source_name in SOURCE_ORDER:
            frame = self._read_source(source_name)
            mapping = mappings[source_name]
            if set(mapping) != set(OUTPUT_COLUMNS):
                raise AssertionError(f"{source_name} mapping must define every canonical field")
            missing_columns = set(mapping.values()) - set(frame.columns)
            if missing_columns:
                raise AssertionError(f"{source_name} is missing mapped columns: {sorted(missing_columns)}")
            for source_row in frame.to_dict(orient="records"):
                row = {
                    field: self._normalize(source_name, field, source_row.get(source_column))
                    for field, source_column in mapping.items()
                }
                user_id = row["user_id"]
                if user_id is None:
                    raise AssertionError(f"{source_name} contains a record without user_id")
                per_user = records.setdefault(user_id, {})
                if source_name in per_user:
                    raise AssertionError(f"{source_name} contains duplicate user_id {user_id}")
                per_user[source_name] = row
        return records

    def _derive_expected(self) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        merged_rows: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for user_id in sorted(self.records):
            by_source = self.records[user_id]
            merged = {"user_id": user_id}
            for field in VALUE_FIELDS:
                values = {
                    source_name: by_source[source_name][field]
                    for source_name in SOURCE_ORDER
                    if source_name in by_source and by_source[source_name][field] is not None
                }
                selected = next(iter(values.values()), None)
                merged[field] = selected
                if len(set(values.values())) > 1:
                    conflicts.append(
                        {
                            "user_id": user_id,
                            "field": field,
                            "values": values,
                            "selected": selected,
                        }
                    )
            merged_rows.append(merged)
        frame = pd.DataFrame(merged_rows, columns=OUTPUT_COLUMNS)
        return frame, sorted(conflicts, key=lambda item: (item["user_id"], item["field"]))

    def _fixture_mechanism_counts(self) -> tuple[int, int]:
        overlap_users = 0
        backfilled_fields = 0
        for by_source in self.records.values():
            if len(by_source) > 1:
                overlap_users += 1
            present_sources = [source for source in SOURCE_ORDER if source in by_source]
            if not present_sources:
                continue
            for field in VALUE_FIELDS:
                if by_source[present_sources[0]][field] is None and any(
                    by_source[source][field] is not None for source in present_sources[1:]
                ):
                    backfilled_fields += 1
        return overlap_users, backfilled_fields

    def _actual_frame(self) -> pd.DataFrame:
        frame = pd.read_parquet(MERGED_PATH)
        return frame.sort_values("user_id").reset_index(drop=True)

    def _actual_records(self) -> list[dict[str, Any]]:
        records = []
        for row in self._actual_frame().to_dict(orient="records"):
            records.append({field: _python_scalar(row.get(field)) for field in OUTPUT_COLUMNS})
        return records

    def _actual_report(self) -> dict[str, Any]:
        return json.loads(CONFLICTS_PATH.read_text(encoding="utf-8"))

    def assert_files_and_schema(self) -> None:
        assert MERGED_PATH.is_file(), "missing /app/merged_users.parquet"
        assert CONFLICTS_PATH.is_file(), "missing /app/conflicts.json"
        frame = self._actual_frame()
        assert tuple(frame.columns) == OUTPUT_COLUMNS
        assert is_integer_dtype(frame["user_id"].dtype)
        report = self._actual_report()
        assert set(report) == {"total_conflicts", "conflicts"}
        assert isinstance(report["total_conflicts"], int)
        assert isinstance(report["conflicts"], list)

    def assert_user_coverage(self) -> None:
        frame = self._actual_frame()
        expected_ids = sorted(self.records)
        assert len(frame) == len(expected_ids)
        assert frame["user_id"].is_unique
        assert frame["user_id"].astype(int).tolist() == expected_ids

    def assert_merged_content(self) -> None:
        expected = [
            {field: _python_scalar(row[field]) for field in OUTPUT_COLUMNS}
            for row in self.expected_frame.to_dict(orient="records")
        ]
        assert self._actual_records() == expected

    def assert_normalized_output(self) -> None:
        for row in self._actual_records():
            if row["created_date"] is not None:
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["created_date"])
            if row["status"] is not None:
                assert row["status"] in set(self.status_map.values())
            if row["name"] is not None:
                assert row["name"] == row["name"].strip()
                if self.name_mode == "title":
                    assert row["name"] == " ".join(row["name"].split()).title()
            if row["email"] is not None:
                assert row["email"] == row["email"].strip()
                if self.email_mode == "lower":
                    assert row["email"] == row["email"].casefold()

    def assert_conflicts(self) -> None:
        report = self._actual_report()
        actual = sorted(report["conflicts"], key=lambda item: (item["user_id"], item["field"]))
        assert report["total_conflicts"] == len(actual)
        assert actual == self.expected_conflicts
        assert len({(item["user_id"], item["field"]) for item in actual}) == len(actual)

    def assert_mechanism_density(self) -> None:
        assert self.overlap_users >= self.contract["minimum_overlap_users"]
        assert self.backfilled_fields >= self.contract["minimum_backfilled_fields"]
        assert len(self.expected_conflicts) >= self.contract["minimum_conflicts"]
