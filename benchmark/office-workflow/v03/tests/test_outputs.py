from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from icalendar import Calendar


ROOT = Path("/app/data/calendar")
EXPECTED_NONMEETING = {
    "Bob": {"class", "nap", "lunch", "dinner", "sleeping"},
    "Tom": {"class", "lunch with David", "report to Charlie", "dinner"},
}


def _events(person: str) -> list[object]:
    calendar = Calendar.from_ical((ROOT / f"{person}.ics").read_bytes())
    return [component for component in calendar.walk() if component.name == "VEVENT"]


@pytest.mark.parametrize("person", ["Bob", "Tom"])
def test_original_events_are_preserved(person: str) -> None:
    events = _events(person)
    nonmeeting = [
        event for event in events if str(event.get("summary", "")).lower() != "meeting"
    ]
    assert len(nonmeeting) == 5
    summaries = {str(event.get("summary", "")) for event in nonmeeting}
    assert EXPECTED_NONMEETING[person] <= summaries


@pytest.mark.parametrize("person", ["Bob", "Tom"])
def test_exactly_one_one_hour_meeting_is_added(person: str) -> None:
    meetings = [
        event
        for event in _events(person)
        if str(event.get("summary", "")).lower() == "meeting"
    ]
    assert len(meetings) == 1
    start = meetings[0].decoded("dtstart")
    end = meetings[0].decoded("dtend")
    assert start.date() == date(2024, 5, 1)
    assert end - start == timedelta(hours=1)


def test_both_calendars_use_the_same_slot() -> None:
    slots = []
    for person in ("Bob", "Tom"):
        meeting = next(
            event
            for event in _events(person)
            if str(event.get("summary", "")).lower() == "meeting"
        )
        slots.append((meeting.decoded("dtstart"), meeting.decoded("dtend")))
    assert slots[0] == slots[1]


def test_meeting_does_not_overlap_existing_events() -> None:
    for person in ("Bob", "Tom"):
        events = _events(person)
        meeting = next(
            event
            for event in events
            if str(event.get("summary", "")).lower() == "meeting"
        )
        start = meeting.decoded("dtstart")
        end = meeting.decoded("dtend")
        overlaps = [
            str(event.get("summary", ""))
            for event in events
            if event is not meeting
            and start < event.decoded("dtend")
            and event.decoded("dtstart") < end
        ]
        assert not overlaps, f"{person} meeting overlaps {overlaps!r}"
