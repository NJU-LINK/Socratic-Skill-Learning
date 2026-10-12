from __future__ import annotations

import sys
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from icalendar import Calendar
from PIL import Image, ImageStat


sys.path.insert(0, "/app")
from solve import run


APP = Path("/app")
DATA = APP / "data"
SUBJECT = "Common calendar overlaps — 2024-05-01"
HEADER = "Common overlaps on 2024-05-01 (UTC)"
ORIGINAL_CALENDAR_HASHES = {
    "Bob": "076df89b14370c94d186cfe99730c2ff5734d66c09933b2cf814faa2c58a1082",
    "Tom": "828df279bc5806eb50fd3a5a3a4d69e8237d87b5c903a4f6976fa80fcab2d35d",
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _events(person: str) -> list[tuple[str, datetime, datetime]]:
    calendar = Calendar.from_ical(
        (DATA / "calendar" / f"{person}.ics").read_bytes()
    )
    return [
        (
            str(component.get("summary", "")),
            _utc(component.decoded("dtstart")),
            _utc(component.decoded("dtend")),
        )
        for component in calendar.walk()
        if component.name == "VEVENT"
    ]


def _expected_lines() -> list[str]:
    overlaps = []
    for bob_summary, bob_start, bob_end in _events("Bob"):
        for tom_summary, tom_start, tom_end in _events("Tom"):
            start = max(bob_start, tom_start)
            end = min(bob_end, tom_end)
            if start < end:
                overlaps.append((start, end, bob_summary, tom_summary))
    overlaps.sort(key=lambda pair: (pair[0], pair[1], pair[2], pair[3]))
    return [
        (
            f"{start:%H:%M}-{end:%H:%M} | "
            f"Bob={bob_summary} | Tom={tom_summary}"
        )
        for start, end, bob_summary, tom_summary in overlaps
    ]


def _message(person: str):
    return BytesParser(policy=policy.default).parsebytes(
        (DATA / f"{person}.eml").read_bytes()
    )


@pytest.mark.parametrize(
    ("person", "address"),
    [("Bob", "bob@example.com"), ("Tom", "tom@example.com")],
)
def test_email_headers_and_plain_text_body_are_exact(person: str, address: str) -> None:
    run()
    message = _message(person)
    assert str(message["From"]) == "calendar@example.com"
    assert str(message["To"]) == address
    assert str(message["Subject"]) == SUBJECT
    assert message.get_content_type() == "text/plain"

    body = message.get_content().strip().splitlines()
    assert body == [HEADER, *_expected_lines()]


def test_both_recipients_receive_the_same_derived_overlap_records() -> None:
    run()
    bob = _message("Bob").get_content().strip()
    tom = _message("Tom").get_content().strip()
    assert bob == tom
    assert len(_expected_lines()) == 5


def test_source_calendars_are_not_modified() -> None:
    from hashlib import sha256

    run()
    for person, expected in ORIGINAL_CALENDAR_HASHES.items():
        actual = sha256(
            (DATA / "calendar" / f"{person}.ics").read_bytes()
        ).hexdigest()
        assert actual == expected


def test_summary_jpeg_is_valid_sized_and_nonblank() -> None:
    run()
    output = DATA / "common_events.jpg"
    with Image.open(output) as image:
        image.verify()
    with Image.open(output) as image:
        assert image.format == "JPEG"
        assert image.size == (1200, 700)
        extrema = ImageStat.Stat(image.convert("RGB")).extrema
        assert any(high - low > 40 for low, high in extrema)
        colors = image.convert("RGB").getcolors(maxcolors=1200 * 700)
        assert colors is not None and len(colors) > 20
