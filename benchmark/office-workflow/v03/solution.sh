#!/usr/bin/env bash
set -euo pipefail

cat > /app/solve.py <<'PY'
from datetime import datetime, timezone
from pathlib import Path

from icalendar import Calendar, Event


CALENDARS = [Path("data/calendar/Bob.ics"), Path("data/calendar/Tom.ics")]
MEETING_START = datetime(2024, 5, 1, 15, 0, tzinfo=timezone.utc)
MEETING_END = datetime(2024, 5, 1, 16, 0, tzinfo=timezone.utc)


def run() -> None:
    for path in CALENDARS:
        calendar = Calendar.from_ical(path.read_bytes())
        calendar.subcomponents = [
            component
            for component in calendar.subcomponents
            if not (
                component.name == "VEVENT"
                and str(component.get("summary", "")).lower() == "meeting"
            )
        ]
        event = Event()
        event.add("summary", "meeting")
        event.add("dtstart", MEETING_START)
        event.add("dtend", MEETING_END)
        event.add("uid", f"shared-meeting-{path.stem.lower()}@example.org")
        calendar.add_component(event)
        path.write_bytes(calendar.to_ical())


if __name__ == "__main__":
    run()
PY

python3 /app/solve.py
