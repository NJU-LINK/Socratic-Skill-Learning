from __future__ import annotations

import sys
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path

import openpyxl
import pytest
from icalendar import Calendar


APP = Path("/app")
SOURCE = APP / "data/team_training_schedule.xlsx"


def _expected_groups() -> dict[str, tuple[tuple[str, str, str], str]]:
    workbook = openpyxl.load_workbook(SOURCE, data_only=True)
    rows = []
    for row_number, row in enumerate(
        workbook.active.iter_rows(min_row=2, values_only=True),
        start=2,
    ):
        name, section, time_range, score = row
        rows.append((row_number, str(name), str(section), str(time_range), float(score)))

    available_a = [row for row in rows if row[2] == "Section A"]
    available_b = [row for row in rows if row[2] == "Section B"]
    section_c = [row for row in rows if row[2] == "Section C"]
    by_name = {}
    for member_c in section_c:
        member_a = min(available_a, key=lambda row: (abs(row[4] - member_c[4]), row[0]))
        member_b = min(available_b, key=lambda row: (abs(row[4] - member_c[4]), row[0]))
        available_a.remove(member_a)
        available_b.remove(member_b)
        names = (member_a[1], member_b[1], member_c[1])
        for name in names:
            by_name[name] = (names, member_c[3])
    return by_name


EXPECTED = _expected_groups()

sys.path.insert(0, "/app")
from solve import run


def test_calendar_artifact_set_is_exact() -> None:
    run()
    assert {path.stem for path in (APP / "calendar").glob("*.ics")} == set(EXPECTED)


def test_email_artifact_set_is_exact() -> None:
    run()
    actual = {
        path.parent.name
        for path in (APP / "emails").glob("*/helping.eml")
    }
    assert actual == set(EXPECTED)


@pytest.mark.parametrize(("name", "case"), sorted(EXPECTED.items()))
def test_calendar_matches_group(name: str, case: tuple[tuple[str, str, str], str]) -> None:
    run()
    names, time_range = case
    calendar = Calendar.from_ical((APP / f"calendar/{name}.ics").read_bytes())
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    assert len(events) == 1
    event = events[0]
    event_text = " ".join(
        [str(event.get("summary", "")), str(event.get("description", ""))]
    )
    assert all(group_name in event_text for group_name in names)

    start_text, end_text = [part.strip() for part in time_range.split(" - ", 1)]
    expected_start = datetime.strptime(start_text, "%I:%M %p").time()
    expected_end = datetime.strptime(end_text, "%I:%M %p").time()
    actual_start = event.decoded("dtstart")
    actual_end = event.decoded("dtend")
    assert actual_start.date() == date(2024, 5, 8)
    assert actual_end.date() == date(2024, 5, 8)
    assert actual_start.time() == expected_start
    assert actual_end.time() == expected_end


@pytest.mark.parametrize(("name", "case"), sorted(EXPECTED.items()))
def test_email_matches_group(name: str, case: tuple[tuple[str, str, str], str]) -> None:
    run()
    names, time_range = case
    message = BytesParser(policy=policy.default).parsebytes(
        (APP / f"emails/{name}/helping.eml").read_bytes()
    )
    body = message.get_body(preferencelist=("plain",))
    body_text = body.get_content() if body is not None else str(message.get_payload())
    assert str(message["Subject"]) == "Helping section"
    assert all(group_name in body_text for group_name in names)
    assert time_range in body_text
