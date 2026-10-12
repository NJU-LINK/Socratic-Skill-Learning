from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import openpyxl
import pytest
from icalendar import Calendar


DATA = Path("/app/data")
CALENDAR_ROOT = Path("/app/calendar")
SOURCE = DATA / "class_member.xlsx"

sys.path.insert(0, "/app")
from solve import run


def _enrollments() -> Counter[tuple[str, int]]:
    sheet = openpyxl.load_workbook(SOURCE, data_only=True).active
    return Counter(
        (str(name), int(class_number))
        for name, class_number in sheet.iter_rows(min_row=2, values_only=True)
        if name not in (None, "") and class_number not in (None, "")
    )


ENROLLMENTS = _enrollments()
BY_CLASS: dict[int, dict[str, int]] = defaultdict(dict)
for (student_name, class_number), occurrence_count in ENROLLMENTS.items():
    BY_CLASS[class_number][student_name] = occurrence_count


@pytest.fixture(scope="module", autouse=True)
def _generate_outputs() -> None:
    run()


def _expected_facts(name: str, class_number: int, count: int) -> str:
    return (
        f"Name: {name}\n"
        f"Class: {class_number}\n"
        f"Source rows: {count}\n"
    )


def test_class_directory_inventory_is_exact() -> None:
    expected = {f"class_{class_number}" for class_number in BY_CLASS}
    actual_data = {
        path.name for path in DATA.glob("class_*") if path.is_dir()
    }
    actual_calendar = {
        path.name for path in CALENDAR_ROOT.glob("class_*") if path.is_dir()
    }
    assert actual_data == expected
    assert actual_calendar == expected


@pytest.mark.parametrize("class_number", sorted(BY_CLASS))
def test_class_text_roster_is_complete_and_deduplicated(class_number: int) -> None:
    expected_names = set(BY_CLASS[class_number])
    directory = DATA / f"class_{class_number}"
    assert {path.stem for path in directory.glob("*.txt")} == expected_names
    for name, count in BY_CLASS[class_number].items():
        assert (directory / f"{name}.txt").read_text(
            encoding="utf-8"
        ) == _expected_facts(name, class_number, count)


@pytest.mark.parametrize("class_number", sorted(BY_CLASS))
def test_class_calendars_are_complete_and_synchronized(class_number: int) -> None:
    expected_names = set(BY_CLASS[class_number])
    directory = CALENDAR_ROOT / f"class_{class_number}"
    assert {path.stem for path in directory.glob("*.ics")} == expected_names

    expected_start = datetime(
        2026,
        9,
        1,
        8 + class_number,
        0,
        0,
        tzinfo=timezone.utc,
    )
    for name, count in BY_CLASS[class_number].items():
        calendar = Calendar.from_ical((directory / f"{name}.ics").read_bytes())
        events = [component for component in calendar.walk() if component.name == "VEVENT"]
        assert len(events) == 1
        event = events[0]
        assert str(event["summary"]) == f"{name} - Class {class_number} orientation"
        assert event.decoded("dtstart") == expected_start
        assert event.decoded("dtend") == expected_start + timedelta(minutes=50)
        assert str(event["uid"]) == (
            f"{name.lower()}-class-{class_number}@class-member.local"
        )
        assert str(event["description"]) + "\n" == _expected_facts(
            name,
            class_number,
            count,
        )


def test_run_is_idempotent() -> None:
    before = {
        path.relative_to(Path("/app")): path.read_bytes()
        for root in (DATA, CALENDAR_ROOT)
        for path in root.rglob("*")
        if path.is_file() and path != SOURCE
    }

    run()
    after = {
        path.relative_to(Path("/app")): path.read_bytes()
        for root in (DATA, CALENDAR_ROOT)
        for path in root.rglob("*")
        if path.is_file() and path != SOURCE
    }
    assert after == before
