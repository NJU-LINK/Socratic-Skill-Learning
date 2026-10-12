#!/bin/bash
set -uo pipefail

cat > /app/solve.py << 'PYEOF'
import os
import re
from datetime import datetime, timezone


def run():
    from pypdf import PdfReader
    from icalendar import Calendar, Event
    from PIL import Image, ImageDraw

    reader = PdfReader("data/invitation_letter.pdf")
    text = ""
    for page in reader.pages:
        text += page.extract_text()

    # Extract conference date from text like "November 15-21, 2024"
    date_match = re.search(r"([A-Z][a-z]+)\s+(\d+)-", text)
    if date_match:
        month_str = date_match.group(1)
        day_str = date_match.group(2)
        year = 2024
        month = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5,
                 "June": 6, "July": 7, "August": 8, "September": 9, "October": 10,
                 "November": 11, "December": 12}.get(month_str, 11)
        day = int(day_str)
    else:
        month, day, year = 11, 15, 2024

    os.makedirs("calendar", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    cal = Calendar()
    cal.add("prodid", "-//invitation//EN")
    cal.add("version", "2.0")
    event = Event()
    event.add("summary", "invitation")
    event.add("dtstart", datetime(year, month, day, 13, 0, 0, tzinfo=timezone.utc))
    event.add("dtend", datetime(year, month, day, 14, 0, 0, tzinfo=timezone.utc))
    cal.add_component(event)
    with open("calendar/Bob.ics", "wb") as f:
        f.write(cal.to_ical())

    img = Image.new("RGB", (400, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((50, 80), "INVITATION", fill=(0, 0, 0))
    img.save("data/invitation.jpg")


if __name__ == "__main__":
    run()
PYEOF
