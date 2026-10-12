#!/usr/bin/env bash
set -euo pipefail

cat > /app/solve.py <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from icalendar import Calendar
from PIL import Image, ImageDraw, ImageFont


CALENDAR_ROOT = Path("data/calendar")
OUTPUT_ROOT = Path("data")
SUBJECT = "Common calendar overlaps — 2024-05-01"
HEADER = "Common overlaps on 2024-05-01 (UTC)"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _events(person: str) -> list[tuple[str, datetime, datetime]]:
    calendar = Calendar.from_ical((CALENDAR_ROOT / f"{person}.ics").read_bytes())
    return [
        (
            str(component.get("summary", "")),
            _utc(component.decoded("dtstart")),
            _utc(component.decoded("dtend")),
        )
        for component in calendar.walk()
        if component.name == "VEVENT"
    ]


def _overlaps() -> list[tuple[datetime, datetime, str, str]]:
    pairs = []
    for bob_summary, bob_start, bob_end in _events("Bob"):
        for tom_summary, tom_start, tom_end in _events("Tom"):
            start = max(bob_start, tom_start)
            end = min(bob_end, tom_end)
            if start < end:
                pairs.append((start, end, bob_summary, tom_summary))
    return sorted(pairs, key=lambda pair: (pair[0], pair[1], pair[2], pair[3]))


def _lines(pairs: list[tuple[datetime, datetime, str, str]]) -> list[str]:
    return [
        (
            f"{start:%H:%M}-{end:%H:%M} | "
            f"Bob={bob_summary} | Tom={tom_summary}"
        )
        for start, end, bob_summary, tom_summary in pairs
    ]


def _write_email(recipient: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = "calendar@example.com"
    message["To"] = f"{recipient.lower()}@example.com"
    message["Subject"] = SUBJECT
    message.set_content(body)
    (OUTPUT_ROOT / f"{recipient}.eml").write_bytes(message.as_bytes())


def _write_image(lines: list[str]) -> None:
    image = Image.new("RGB", (1200, 700), "#f7f9fc")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.load_default(size=34)
    row_font = ImageFont.load_default(size=24)

    draw.text((60, 45), SUBJECT.replace("—", "-"), fill="#102a43", font=title_font)
    for index, line in enumerate(lines):
        top = 125 + index * 100
        fill = "#d9eafd" if index % 2 == 0 else "#e9f5ee"
        draw.rounded_rectangle(
            (50, top, 1150, top + 70),
            radius=12,
            fill=fill,
            outline="#486581",
            width=2,
        )
        draw.text((75, top + 21), line, fill="#102a43", font=row_font)

    image.save(OUTPUT_ROOT / "common_events.jpg", format="JPEG", quality=92)


def run() -> None:
    pairs = _overlaps()
    lines = _lines(pairs)
    body = "\n".join([HEADER, *lines, ""])
    _write_email("Bob", body)
    _write_email("Tom", body)
    _write_image(lines)


if __name__ == "__main__":
    run()
PY

python3 /app/solve.py
