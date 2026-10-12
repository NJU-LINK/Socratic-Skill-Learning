from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

from icalendar import Calendar
from PIL import Image
from pypdf import PdfReader


sys.path.insert(0, "/app")
from solve import run


APP = Path("/app")


def _conference_date() -> datetime:
    text = " ".join(
        page.extract_text() or ""
        for page in PdfReader(APP / "data/invitation_letter.pdf").pages
    )
    match = re.search(r"([A-Z][a-z]+)\s+(\d+)-\d+,\s+(\d{4})", text)
    assert match
    return datetime.strptime(
        f"{match.group(1)} {match.group(2)} {match.group(3)}",
        "%B %d %Y",
    )


def test_calendar_has_one_invitation_on_extracted_date() -> None:
    run()
    calendar = Calendar.from_ical((APP / "calendar/Bob.ics").read_bytes())
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    assert len(events) == 1
    event = events[0]
    assert "invitation" in str(event.get("summary", "")).lower()
    assert event.decoded("dtstart").date() == _conference_date().date()
    assert event.decoded("dtend") > event.decoded("dtstart")


def test_jpeg_is_valid_and_nontrivial() -> None:
    run()
    with Image.open(APP / "data/invitation.jpg") as image:
        image.verify()
    with Image.open(APP / "data/invitation.jpg") as image:
        assert image.format == "JPEG"
        assert image.width >= 200 and image.height >= 100
