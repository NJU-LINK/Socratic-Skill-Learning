---
name: office-workflow
description: >
  General skill for office automation workflows that read, transform, filter,
  route, and produce office artifacts (email, calendar, PDF, XLSX, DOCX, TXT,
  JSON, images). Covers MIME-aware email parsing, iCalendar manipulation,
  PDF/XLSX reading and writing, format conversion, relevance filtering,
  scheduling, extraction, quantitative analysis, and multi-format output with
  cross-artifact consistency and preservation constraints.
---

# Office Workflow Skill

## Overview

This skill addresses a family of office automation tasks where the agent must:
1. **Parse** one or more source office artifacts (email, calendar, spreadsheet, PDF)
2. **Apply** a workflow relation (filtering, extraction, scheduling, routing, analysis, summarization)
3. **Produce** destination artifacts in specified formats (TXT, ICS, DOCX, PDF, EML, JSON, JPEG)
4. **Preserve** existing content integrity and maintain cross-output consistency

## General Workflow Pattern

Every task in this family follows a common structure:

```
1. DISCOVER: Find all source files in the specified directory/directories
2. PARSE: Read each source with the appropriate format-aware parser
3. FILTER/SELECT: Apply the selection criteria (subject match, date range, recipient, etc.)
4. TRANSFORM: Extract, convert, analyze, or restructure the data as required
5. OUTPUT: Write destination artifacts in the specified format(s)
6. VERIFY: Ensure preservation constraints and cross-output consistency
```

### Implementation Template

```python
import os
from pathlib import Path

def run():
    # Ensure working directory is the project root
    # Tests may call run() from any directory
    os.chdir("/app")  # or detect dynamically: os.chdir(Path(__file__).parent)
    
    # 1. Discover source files
    source_dir = Path("data/...")  # as specified
    source_files = sorted(source_dir.glob("*.ext"))  # appropriate extension
    
    # 2-3. Parse and filter
    selected = []
    for fpath in source_files:
        data = parse_file(fpath)
        if matches_criteria(data):
            selected.append(data)
    
    # 4. Transform
    results = transform(selected)
    
    # 5. Output
    write_outputs(results)

# Tests call: from solve import run; run()
```

### Task Decomposition Strategy

When facing a new task variant, decompose it into these questions:

1. **What are the sources?** (email, calendar, spreadsheet, PDF — check `data/` directory)
2. **What is the workflow relation?** (filter, extract, schedule, route, analyze, summarize)
3. **What are the destinations?** (txt, ics, docx, pdf, eml, json, jpeg — check task instruction)
4. **What are the constraints?** (sorting, formatting, preservation, routing rules)
5. **Are there multiple outputs?** If yes, ensure cross-format consistency

Then map to patterns:
- Email filtering → MIME parsing + relevance filtering + text output
- Calendar scheduling → iCalendar parsing + free-time calculation + iCalendar output
- Spreadsheet extraction → XLSX parsing + fact extraction + JSON/text output
- Multi-source reconciliation → parse all sources + reconcile + produce outputs
- Cross-format outputs → unified data + cross-format consistency pattern

---

## Input Parsing Recipes

### MIME Email (.eml)

Use Python's `email` module with `policy.default` for modern header handling.

#### Understanding the MIME Tree (Critical Mechanism)

An `.eml` file represents a **MIME tree**. A typical multipart email has this structure:

```
message (multipart/mixed)
├── headers (From, To, Subject, ...)
└── body part (text/plain) ← the actual content
```

More complex emails can nest deeper:

```
message (multipart/mixed)
├── headers
├── part (multipart/alternative)
│   ├── text/plain
│   └── text/html
└── attachment (image/png)
```

**The critical invariant: always navigate to the leaf part before calling `get_content()`.**

- `msg.get_body(preferencelist=("plain",))` **walks the MIME tree** and returns the best-matching body leaf node — a single `EmailMessage` part.
- `msg.get_content()` called directly on a **multipart** message would call `str()` on each child part and concatenate them, giving you MIME boundaries, headers, and garbage mixed in.
- When the message is NOT multipart (just a single text/plain part), `get_body()` returns the message itself, and calling `get_content()` on it returns the decoded text. This is why the fallback pattern works.

#### What "Stripped" Body Means Mechanically

`get_content()` on a text/plain MIME part returns the decoded content between the MIME boundaries. This content typically ends with `\n` (the line break before the boundary marker). For example, the raw decoded string might be:

```
'Can we have a zoom meeting later today?\n\nSent at: 2024-03-23 10:00:00\n'
```

The **minimal correct stripping operation** is `body.rstrip()` on the whole string, which removes the trailing `\n`:

```
'Can we have a zoom meeting later today?\n\nSent at: 2024-03-23 10:00:00'
```

**Internal blank lines are content, not formatting.** The `\n\n` between the message text and "Sent at:" is part of the original message and must be preserved. Only strip trailing whitespace from the whole body string.

#### Email Parsing Code

```python
import email
from email import policy
from pathlib import Path

def parse_eml(filepath):
    """Parse a .eml file into structured components."""
    with open(filepath, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    
    result = {
        "from": msg["From"],
        "to": msg["To"],
        "subject": msg["Subject"],  # decoded automatically with policy.default
        "date": msg["Date"],
        "filename": filepath.name,
    }
    
    # CRITICAL: Navigate to the leaf body part before calling get_content()
    # get_body() walks the MIME tree to find the best-matching leaf node
    body_part = msg.get_body(preferencelist=("plain",))
    if body_part:
        # get_content() on a leaf text part returns decoded text
        result["body"] = body_part.get_content()
    else:
        # No plain text part found — try HTML as fallback
        # This handles HTML-only emails (common in real-world scenarios)
        html_part = msg.get_body(preferencelist=("html",))
        if html_part:
            # Convert HTML to plain text (basic conversion)
            import html as html_module
            html_content = html_part.get_content()
            # Strip HTML tags and decode entities
            import re
            text = re.sub(r'<[^>]+>', ' ', html_content)
            text = html_module.unescape(text)
            # Normalize whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            result["body"] = text
        else:
            # No body at all (rare edge case)
            result["body"] = ""
    
    # Strip trailing whitespace (the \n before the MIME boundary)
    result["body_stripped"] = result["body"].rstrip()
    
    # Extract HTML body if needed (same tree-walking principle)
    html_part = msg.get_body(preferencelist=("html",))
    if html_part:
        result["html"] = html_part.get_content()
    
    # Extract attachments by walking the tree
    attachments = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            attachments.append({
                "filename": part.get_filename(),
                "content_type": part.get_content_type(),
                "payload": part.get_payload(decode=True),
            })
    result["attachments"] = attachments
    
    return result
```

**Key points:**
- Always use `policy=policy.default` for proper header decoding
- Use `get_body(preferencelist=("plain",))` to walk the MIME tree to the leaf body part
- Never call `get_content()` directly on a multipart message — navigate to the leaf first
- **Critical fallback**: If no plain text part exists, try HTML and convert to text. Never call `msg.get_content()` on a multipart message as it produces garbage.
- Subject comparison should be exact string match unless task says otherwise
- Sort selected messages by source filename (the `.eml` filename)

### Bridging Email Attachments to Format Parsers

Email attachments are extracted as raw bytes via `get_payload(decode=True)`. To process them with format-specific parsers, you need to bridge the bytes to the appropriate library. This is critical for scheduling variants where meeting invites arrive as `.ics` attachments.

```python
import io
import icalendar
from pypdf import PdfReader
import openpyxl

def parse_attachment(attachment):
    """Feed an email attachment's bytes to the appropriate parser.
    
    Args:
        attachment: dict with keys "filename", "content_type", "payload" (bytes)
    
    Returns:
        Parsed content appropriate to the attachment type
    """
    content_type = attachment["content_type"]
    payload = attachment["payload"]  # bytes from get_payload(decode=True)
    
    if content_type == "text/calendar":
        # icalendar.Calendar.from_ical() accepts bytes directly
        cal = icalendar.Calendar.from_ical(payload)
        events = []
        for component in cal.walk():
            if component.name == "VEVENT":
                events.append({
                    "summary": str(component.get("SUMMARY", "")),
                    "dtstart": component.get("DTSTART").dt if component.get("DTSTART") else None,
                    "dtend": component.get("DTEND").dt if component.get("DTEND") else None,
                    "location": str(component.get("LOCATION", "")),
                    "description": str(component.get("DESCRIPTION", "")),
                    "uid": str(component.get("UID", "")),
                })
        return {"type": "calendar", "events": events, "raw": cal}
    
    elif content_type == "application/pdf":
        # PdfReader needs a file-like object — wrap bytes in BytesIO
        reader = PdfReader(io.BytesIO(payload))
        text = "\n".join(page.extract_text() for page in reader.pages)
        return {"type": "pdf", "text": text, "num_pages": len(reader.pages)}
    
    elif content_type in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          "application/vnd.ms-excel"):
        # openpyxl needs a file-like object too
        wb = openpyxl.load_workbook(io.BytesIO(payload), data_only=True)
        sheets = {}
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            sheets[sheet_name] = {"headers": list(rows[0]) if rows else [], "rows": rows}
        return {"type": "xlsx", "workbook": wb, "sheets": sheets}
    
    elif content_type.startswith("text/"):
        # Plain text attachment
        return {"type": "text", "content": payload.decode("utf-8", errors="replace")}
    
    return {"type": "unknown", "payload": payload}

# Usage example: extract calendar attachments from emails
def extract_calendar_attachments(emails):
    """Extract and parse calendar attachments from email messages."""
    all_events = []
    for msg in emails:
        for att in msg.get("attachments", []):
            if att["content_type"] == "text/calendar":
                parsed = parse_attachment(att)
                all_events.extend(parsed["events"])
    return all_events
```

**Key insight:** The bridge mechanism differs by library:
- `icalendar.Calendar.from_ical()` accepts `bytes` directly
- `pypdf.PdfReader` and `openpyxl.load_workbook` need a file-like object → use `io.BytesIO(bytes)`
- This is the same mechanism as reading from disk (`open(filepath, "rb")` gives a file object), just in-memory

### iCalendar (.ics)

Use the `icalendar` library:

```python
import icalendar
from pathlib import Path

def parse_ics(filepath):
    """Parse an .ics file into a list of events."""
    with open(filepath, "rb") as f:
        cal = icalendar.Calendar.from_ical(f.read())
    
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            event = {
                "summary": str(component.get("SUMMARY", "")),
                "dtstart": component.get("DTSTART").dt if component.get("DTSTART") else None,
                "dtend": component.get("DTEND").dt if component.get("DTEND") else None,
                "location": str(component.get("LOCATION", "")),
                "description": str(component.get("DESCRIPTION", "")),
                "uid": str(component.get("UID", "")),
                "attendees": [],
                "raw": component,  # keep raw component for reconstruction
            }
            # Handle multiple attendees
            attendees = component.get("ATTENDEE")
            if attendees:
                if not isinstance(attendees, list):
                    attendees = [attendees]
                event["attendees"] = [str(a) for a in attendees]
            events.append(event)
    
    return {"calendar": cal, "events": events}
```

**Key points:**
- `DTSTART`/`DTEND` `.dt` property gives datetime or date objects
- Preserve the original calendar object for modification/re-serialization
- Use `cal.to_ical()` to serialize back to .ics format
- Timezone-aware datetimes must be handled carefully

### XLSX Spreadsheets

Use `openpyxl`:

```python
import openpyxl
from pathlib import Path

def parse_xlsx(filepath):
    """Parse an .xlsx file into structured data."""
    wb = openpyxl.load_workbook(filepath, data_only=True)
    sheets = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        headers = None
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = list(row)
            rows.append(list(row))
        sheets[sheet_name] = {"headers": headers, "rows": rows}
    return {"workbook": wb, "sheets": sheets}
```

### PDF Documents

Use `pypdf` for text extraction:

```python
from pypdf import PdfReader
from pathlib import Path

def parse_pdf(filepath):
    """Extract text and metadata from a PDF."""
    reader = PdfReader(filepath)
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text())
    return {
        "pages": pages,
        "full_text": "\n".join(pages),
        "metadata": reader.metadata,
        "num_pages": len(reader.pages),
    }
```

---

## Output Writing Recipes

### Plain Text (.txt)

```python
def write_txt(filepath, blocks):
    """Write structured text blocks to a .txt file.
    
    blocks: list of formatted strings, each WITHOUT a trailing newline.
    Example block: "Subject: scheduled meeting\nCan we have a zoom meeting..."
    
    Blocks are joined by "\n\n" (one blank line between them).
    File ends with exactly one "\n".
    """
    with open(filepath, "w") as f:
        f.write("\n\n".join(blocks) + "\n")
```

#### Understanding Block Separators vs. Internal Blank Lines

This is the most subtle formatting issue in the family. After stripping, a body may contain internal blank lines (content), e.g.:

```
Can we have a zoom meeting later today?
                                      ← internal blank line (content, preserved)
Sent at: 2024-03-23 10:00:00
```

When writing blocks, the "one blank line" separator between blocks is visually indistinguishable from internal blank lines within a body. The correct approach:

**Each block is `{header}\n{body}` (NO trailing newline). Blocks are joined by `"\n\n"`. The file gets exactly one terminal `"\n"`.**

The exact byte structure for a two-block output:
```
Subject: scheduled meeting\n          ← header line
Can we have a zoom meeting later today?\n   ← body line 1
\n                                     ← internal blank line (content)
Sent at: 2024-03-23 10:00:00          ← body last line (no trailing \n in block)
\n\n                                   ← "\n\n" separator between blocks
Subject: application approved\n       ← header line
Your scholarship application has been approved.\n  ← body line 1
\n                                     ← internal blank line (content)
Sent at: 2024-04-02 10:00:00\n        ← terminal "\n" from the + "\n"
```

The cleaner implementation pattern:

```python
blocks = []
for msg_data in selected:
    body = msg_data["body_part"].get_content().rstrip()  # strip trailing \n only
    block = f"Subject: {msg_data['subject']}\n{body}"     # no trailing \n
    blocks.append(block)

with open(output_path, "w") as f:
    f.write("\n\n".join(blocks) + "\n")  # join with blank line, end with \n
```

This makes the structure obvious: blocks are joined by `"\n\n"` (which creates one blank line since each block ends without a trailing newline), and the file gets exactly one terminal `"\n"`.

**Key formatting rules (common across tasks):**
- "Stripped" body means `body.rstrip()` — remove trailing whitespace from the whole string, preserve internal blank lines
- Separate adjacent blocks with one blank line (`"\n\n"` between blocks)
- End the file with exactly one newline (`+ "\n"`)
- Do NOT add extra headers or footers unless specified

### iCalendar (.ics)

```python
import icalendar
import datetime

def create_ics(events, cal_name="Calendar"):
    """Create an .ics calendar from event dicts."""
    cal = icalendar.Calendar()
    cal.add("prodid", "-//Office Workflow//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", cal_name)
    
    for ev in events:
        event = icalendar.Event()
        event.add("summary", ev["summary"])
        event.add("dtstart", ev["dtstart"])
        if "dtend" in ev:
            event.add("dtend", ev["dtend"])
        if "location" in ev:
            event.add("location", ev["location"])
        if "description" in ev:
            event.add("description", ev["description"])
        if "uid" in ev:
            event.add("uid", ev["uid"])
        cal.add_component(event)
    
    return cal.to_ical()

def write_ics(filepath, events, **kwargs):
    data = create_ics(events, **kwargs)
    with open(filepath, "wb") as f:
        f.write(data)
```

### DOCX

```python
import docx

def write_docx(filepath, content_blocks):
    """Write content blocks to a .docx file."""
    doc = docx.Document()
    for block in content_blocks:
        if "heading" in block:
            doc.add_heading(block["heading"], level=block.get("level", 1))
        if "paragraph" in block:
            doc.add_paragraph(block["paragraph"])
        if "table_data" in block:
            table = doc.add_table(rows=1, cols=len(block["table_data"][0]))
            for i, val in enumerate(block["table_data"][0]):
                table.rows[0].cells[i].text = str(val)
            for row_data in block["table_data"][1:]:
                row = table.add_row()
                for i, val in enumerate(row_data):
                    row.cells[i].text = str(val)
    doc.save(filepath)
```

### PDF (with reportlab)

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def write_pdf(filepath, lines, title=None):
    """Write text lines to a PDF."""
    c = canvas.Canvas(filepath, pagesize=letter)
    y = 750  # start from top
    if title:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, y, title)
        y -= 30
    c.setFont("Helvetica", 11)
    for line in lines:
        if y < 50:
            c.showPage()
            y = 750
            c.setFont("Helvetica", 11)
        c.drawString(72, y, line)
        y -= 15
    c.save()
```

### Email (.eml)

```python
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import datetime

def create_eml(from_addr, to_addr, subject, body, date=None):
    """Create an email message."""
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    if date:
        msg["Date"] = date
    msg.attach(MIMEText(body, "plain"))
    return msg

def write_eml(filepath, msg):
    """Write an email message to a .eml file."""
    with open(filepath, "wb") as f:
        f.write(msg.as_bytes())
```

### JSON

```python
import json

def write_json(filepath, data, indent=2):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=indent, default=str)
```

### JPEG / Images (with Pillow)

```python
from PIL import Image, ImageDraw, ImageFont

def create_text_image(filepath, text_lines, width=800, height=600):
    """Create a simple text image."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 20
    for line in text_lines:
        draw.text((20, y), line, fill="black")
        y += 20
    img.save(filepath, "JPEG")
```

---

## Date/Time Handling (python-dateutil)

Temporal constraints are a core spec axis (scheduling, free-time windows, date filtering). The `python-dateutil` library is available and essential.

```python
from dateutil import parser as dateutil_parser
from datetime import datetime, date

# Parse any date string into a datetime object
dt = dateutil_parser.parse("2024-03-23 10:00:00")
dt = dateutil_parser.parse("March 23, 2024 at 10am")
dt = dateutil_parser.parse("2024-01-02T03:00:00")

# Distinguish date vs datetime (critical for iCalendar handling)
# iCalendar DTSTART/DTEND can be either type:
#   - datetime: has time component (e.g., meeting at 10:00)
#   - date: date-only, treat as all-day event
def classify_dt(dt_value):
    """Returns 'datetime' or 'date' depending on the type."""
    if isinstance(dt_value, datetime):
        return "datetime"  # has time component
    elif isinstance(dt_value, date):
        return "date"      # date-only, all-day event
    return None

# Sorting and comparing dates
events_sorted = sorted(events, key=lambda e: e["dtstart"])

# Computing intervals (for scheduling / free-time calculations)
from datetime import timedelta
duration = event["dtend"] - event["dtstart"]  # timedelta object
overlap = max(start1, start2) < min(end1, end2)  # check if two intervals overlap
```

**Why this matters:** iCalendar DTSTART/DTEND can be either `date` or `datetime` objects. You cannot directly compare a `date` with a `datetime` — Python will raise a `TypeError`. Additionally, iCalendar events frequently have **timezone-aware** datetimes (e.g., `DTSTART;TZID=America/New_York:20240323T100000`), which cannot be compared with **naive** datetimes (those without timezone info). Always normalize to naive datetimes for uniform comparison:

```python
def normalize_to_datetime(dt_value):
    """Convert date or timezone-aware datetime to naive datetime for uniform comparison.
    
    Strips timezone info without converting — all times treated as local.
    This is appropriate for free-time calculation because working hours are
    always in local time, and the task expects all comparisons in the same timezone.
    """
    if isinstance(dt_value, datetime):
        # Strip timezone info if present — treat as local time
        return dt_value.replace(tzinfo=None)
    elif isinstance(dt_value, date):
        return datetime(dt_value.year, dt_value.month, dt_value.day)
    return dt_value
```

**Critical:** The `.replace(tzinfo=None)` call strips the timezone without converting. This is the right choice for free-time calculation because working hours are always in local time, and the task typically expects all comparisons in the same timezone.

---

## Workflow Relation Patterns

### 1. Relevance Filtering
Select artifacts matching criteria (subject, sender, date, content keywords).

```python
# Pattern: exact subject match
target_subjects = {"scheduled meeting", "application approved"}
selected = [msg for msg in messages if msg["subject"] in target_subjects]

# Pattern: keyword/contains match
selected = [msg for msg in messages if "approved" in msg["subject"].lower()]

# Pattern: recipient-based
selected = [msg for msg in messages if "Bob" in msg["to"]]
```

### 2. Fact/Table Extraction
Extract structured data from documents (tables from XLSX, dates from text, key-value pairs).

```python
# Pattern: extract rows matching criteria from spreadsheet
def extract_rows(sheet_data, column, value):
    headers = sheet_data["headers"]
    col_idx = headers.index(column)
    return [row for row in sheet_data["rows"][1:] if row[col_idx] == value]
```

### 3. Scheduling / Free-Time Calculation
Find common availability across calendars.

**Requires `normalize_to_datetime` from the Date/Time Handling section above.**

```python
import datetime
from datetime import timedelta

def find_free_slots(events_list, working_hours=(9, 17), duration_minutes=60, date_range=None):
    """Find common free time slots across multiple calendars.
    
    Args:
        events_list: list of lists of events (one list per person/calendar)
        working_hours: (start_hour, end_hour) tuple for business hours
        duration_minutes: minimum slot duration in minutes
        date_range: (start_date, end_date) tuple to search within
    
    Returns:
        list of (start_datetime, end_datetime) tuples for available slots
    """
    # Collect all busy intervals
    busy = []
    for events in events_list:
        for ev in events:
            if ev["dtstart"] and ev["dtend"]:
                # Normalize to datetime if needed
                start = normalize_to_datetime(ev["dtstart"])
                end = normalize_to_datetime(ev["dtend"])
                busy.append((start, end))
    
    if not busy:
        # No events — entire working hours are free for the date range
        free_slots = []
        if date_range:
            search_start, search_end = date_range
        else:
            # Default to today
            import datetime as dt_module
            today = dt_module.date.today()
            search_start = today
            search_end = today
        
        current_date = search_start
        while current_date <= search_end:
            day_start = datetime.datetime.combine(current_date, datetime.time(working_hours[0], 0))
            day_end = datetime.datetime.combine(current_date, datetime.time(working_hours[1], 0))
            if day_end > day_start:
                free_slots.append((day_start, day_end))
            current_date += datetime.timedelta(days=1)
        return free_slots
    
    busy.sort(key=lambda x: x[0])
    
    # Merge overlapping intervals
    merged = [busy[0]]
    for start, end in busy[1:]:
        if start <= merged[-1][1]:
            # Overlapping or adjacent, merge
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    
    # Find gaps within working hours
    free_slots = []
    min_duration = timedelta(minutes=duration_minutes)
    
    # Determine date range to search
    if date_range:
        search_start, search_end = date_range
    else:
        # Default: search from earliest event date to latest event date
        search_start = merged[0][0].date()
        search_end = merged[-1][1].date()
    
    current_date = search_start
    while current_date <= search_end:
        # Working hours for this day
        day_start = datetime.datetime.combine(current_date, datetime.time(working_hours[0], 0))
        day_end = datetime.datetime.combine(current_date, datetime.time(working_hours[1], 0))
        
        # Find gaps on this day
        slot_start = day_start
        
        for busy_start, busy_end in merged:
            # Skip if busy interval is not on this day
            if busy_end <= day_start or busy_start >= day_end:
                continue
            
            # Clamp to working hours
            busy_start = max(busy_start, day_start)
            busy_end = min(busy_end, day_end)
            
            # Check for gap before this busy interval
            if slot_start < busy_start:
                gap_duration = busy_start - slot_start
                if gap_duration >= min_duration:
                    free_slots.append((slot_start, busy_start))
            
            # Move slot_start to after this busy interval
            slot_start = max(slot_start, busy_end)
        
        # Check for gap after last busy interval until end of day
        if slot_start < day_end:
            gap_duration = day_end - slot_start
            if gap_duration >= min_duration:
                free_slots.append((slot_start, day_end))
        
        current_date += timedelta(days=1)
    
    return free_slots

def find_common_free_time(calendars, meeting_duration_minutes=60, **kwargs):
    """Find time slots when all calendars are free.
    
    Args:
        calendars: list of parsed calendar dicts (from parse_ics)
        meeting_duration_minutes: required meeting length
    """
    events_per_calendar = [cal["events"] for cal in calendars]
    return find_free_slots(events_per_calendar, duration_minutes=meeting_duration_minutes, **kwargs)
```

### 4. Quantitative Analysis + Visualization
Compute statistics and produce charts/images.

```python
from PIL import Image, ImageDraw

def create_bar_chart(filepath, data, title=""):
    """Create a simple bar chart image. data = [(label, value), ...]"""
    if not data:
        return
    max_val = max(v for _, v in data)
    bar_width = 50
    gap = 20
    chart_height = 300
    width = len(data) * (bar_width + gap) + 100
    height = chart_height + 100
    
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    for i, (label, value) in enumerate(data):
        bar_height = int((value / max_val) * chart_height) if max_val > 0 else 0
        x = 50 + i * (bar_width + gap)
        y = chart_height - bar_height + 20
        draw.rectangle([x, y, x + bar_width, chart_height + 20], fill="steelblue")
        draw.text((x, chart_height + 25), label, fill="black")
    
    img.save(filepath, "JPEG")
```

### 5. Routing and Format Conversion
Route outputs to different destinations based on recipient/content, converting formats.

```python
# Pattern: one output per recipient
def route_by_recipient(messages, output_dir):
    for msg in messages:
        recipient = msg["to"].split("@")[0]  # extract username
        recipient_dir = Path(output_dir) / recipient
        recipient_dir.mkdir(parents=True, exist_ok=True)
        write_output(recipient_dir / f"{msg['filename']}.txt", msg)
```

### 6. Summarization
Produce condensed versions of source content.

```python
def summarize_text(text, max_sentences=3):
    """Simple extractive summary: take first N sentences."""
    sentences = text.replace("\n", " ").split(". ")
    return ". ".join(sentences[:max_sentences]) + "." if sentences else ""
```

### 7. Multi-Source Reconciliation
Combine data from multiple source types (email + calendar + spreadsheet).

```python
def reconcile_sources(email_data, calendar_data, spreadsheet_data):
    """Reconcile data from multiple sources into unified structure.
    
    Example: Extract meeting info from emails, cross-reference with calendar,
    validate against spreadsheet roster.
    """
    # Extract relevant info from each source
    email_meetings = {}
    for msg in email_data:
        if "meeting" in msg["subject"].lower():
            # Extract date from body if present
            email_meetings[msg["filename"]] = {
                "subject": msg["subject"],
                "body": msg["body"],
                "from": msg["from"],
            }
    
    calendar_events = {}
    for event in calendar_data["events"]:
        calendar_events[event["summary"]] = {
            "dtstart": event["dtstart"],
            "dtend": event["dtend"],
            "attendees": event["attendees"],
        }
    
    # Cross-reference: find emails that match calendar events
    reconciled = []
    for filename, email_info in email_meetings.items():
        # Try to match with calendar event
        matching_event = None
        for summary, cal_info in calendar_events.items():
            if email_info["subject"].lower() in summary.lower():
                matching_event = cal_info
                break
        
        reconciled.append({
            "source_file": filename,
            "email_subject": email_info["subject"],
            "email_body": email_info["body"],
            "calendar_match": matching_event,
            "status": "reconciled" if matching_event else "no_calendar_match",
        })
    
    return reconciled
```

### 8. In-Place Calendar Modification
Add events to existing calendars while preserving existing content.

```python
def add_events_to_calendar(existing_cal_path, new_events, output_path=None):
    """Add new events to an existing calendar file.
    
    Args:
        existing_cal_path: path to existing .ics file
        new_events: list of event dicts to add
        output_path: where to write (defaults to overwriting existing)
    """
    if output_path is None:
        output_path = existing_cal_path
    
    # Parse existing calendar
    with open(existing_cal_path, "rb") as f:
        cal = icalendar.Calendar.from_ical(f.read())
    
    # Add new events
    for ev in new_events:
        event = icalendar.Event()
        event.add("summary", ev["summary"])
        event.add("dtstart", ev["dtstart"])
        if "dtend" in ev:
            event.add("dtend", ev["dtend"])
        if "location" in ev:
            event.add("location", ev["location"])
        if "description" in ev:
            event.add("description", ev["description"])
        if "uid" in ev:
            event.add("uid", ev["uid"])
        else:
            # Generate UID if not provided
            import uuid
            event.add("uid", str(uuid.uuid4()))
        cal.add_component(event)
    
    # Write back (preserves all existing events)
    with open(output_path, "wb") as f:
        f.write(cal.to_ical())
```

### 9. Cross-Format Consistency
Ensure the same data appears correctly in multiple output formats.

```python
def produce_consistent_outputs(data, output_specs):
    """Produce multiple output formats from the same data source.
    
    Args:
        data: unified data structure
        output_specs: list of dicts specifying each output format
            Example: [
                {"format": "json", "path": "data/output.json"},
                {"format": "txt", "path": "data/output.txt"},
                {"format": "jpeg", "path": "data/chart.jpeg"},
            ]
    """
    for spec in output_specs:
        fmt = spec["format"]
        path = spec["path"]
        
        if fmt == "json":
            write_json(path, data)
        elif fmt == "txt":
            # Convert data to text blocks
            blocks = []
            for item in data:
                block = f"Subject: {item.get('subject', 'N/A')}\n{item.get('body', '')}"
                blocks.append(block)
            write_txt(path, blocks)
        elif fmt == "jpeg":
            # Create visualization from data
            # Extract numeric data for chart
            chart_data = [(item.get("label", ""), item.get("value", 0)) for item in data]
            create_bar_chart(path, chart_data)
        elif fmt == "ics":
            write_ics(path, data)
        # ... other formats
```

**Key principle:** When producing multiple outputs, always derive them from the same source data structure to ensure consistency. Never manually duplicate data across formats.

---

## Preservation and Consistency Rules

### Critical Invariants

1. **Source preservation**: Never modify source files unless explicitly told to do in-place updates
2. **Complete body text**: When extracting email bodies, include the FULL plain-text body (stripped of leading/trailing whitespace)
3. **Cross-output consistency**: If the same data appears in multiple output formats (e.g., TXT and JSON), the facts must agree exactly
4. **Original calendar events**: When adding events to an existing calendar, preserve all existing events unchanged
5. **Individualized facts**: When producing per-recipient outputs, ensure each recipient's data is correct and consistent across all their output artifacts

### Common Pitfalls

- **Subject encoding**: With `policy.default`, `msg["Subject"]` returns a properly decoded string. Without it, you may get encoded words like `=?utf-8?q?...?=`
- **MIME tree navigation**: Never call `get_content()` on a multipart message — it concatenates child parts with boundaries. Always use `get_body(preferencelist=("plain",))` to walk to the leaf part first, then call `get_content()` on that leaf.
- **Body whitespace**: "Stripped" body means `body.rstrip()` on the whole string — this removes the trailing `\n` that appears before the MIME boundary marker. **Internal blank lines are content, not formatting** — they must be preserved. Do NOT use `strip()` (which would remove leading whitespace) or per-line rstrip unless specifically required.
- **Filename sorting**: Sort by the actual filename string (lexicographic), not by content or date
- **MIME boundaries**: Never manually parse MIME; always use the `email` module
- **Date handling**: iCalendar DTSTART/DTEND can be `date` or `datetime` objects. You cannot directly compare a `date` with a `datetime` (Python raises `TypeError`). Use `normalize_to_datetime()` or check `isinstance()` first. See the Date/Time Handling section.
- **XLSX data types**: `openpyxl` with `data_only=True` returns computed values; without it, you get formulas
- **PDF text extraction**: `pypdf` text extraction may lose formatting; for simple text content it's usually sufficient
- **Block separators**: Use the pattern `"\n\n".join(blocks) + "\n"` where each block is `f"Subject: {subject}\n{body}"` (no trailing newline). This produces one blank line between blocks and exactly one terminal newline. Internal blank lines within a body are preserved as content.

---

## Output Format Specification Patterns

### Text Block Format (common pattern)
```
Subject: <subject>
<body text>

Subject: <subject>
<body text>
```
- Each block: `f"Subject: {subject}\n{body}"` — no trailing newline in the block itself
- Blocks joined by `"\n\n"` — this creates one blank line between blocks
- File ends with exactly one `"\n"` (added after the join)
- Internal blank lines within body text are content, preserved as-is
- No extra headers or footers
- Implementation: `f.write("\n\n".join(blocks) + "\n")`

### Calendar Event Format
```
BEGIN:VEVENT
SUMMARY:...
DTSTART:...
DTEND:...
END:VEVENT
```

### JSON Structure
```json
[
  {
    "subject": "...",
    "body": "...",
    "from": "...",
    "to": "..."
  }
]
```

---

## Verification Checklist

Before finalizing any solution:

- [ ] All source files in the specified directory are discovered
- [ ] Filtering criteria match exactly (exact subject match vs. contains vs. regex)
- [ ] Output is sorted as specified (by filename, date, etc.)
- [ ] Body text is complete and properly stripped
- [ ] Block separators match specification exactly
- [ ] File ends with exactly one newline (for text outputs)
- [ ] Cross-output data is consistent (if multiple outputs — same facts in JSON, TXT, JPEG, etc.)
- [ ] Source files are not modified (unless in-place update required)
- [ ] For in-place calendar updates: all existing events preserved, new events added correctly
- [ ] For multi-source tasks: data from all sources reconciled before output
- [ ] For scheduling tasks: free-time algorithm handles date vs datetime, working hours, minimum duration
- [ ] `run()` function is callable and performs all operations
- [ ] All imports are included in solve.py
- [ ] Output directories created if needed (`os.makedirs(..., exist_ok=True)`)
- [ ] `run()` works regardless of caller's working directory (uses `os.chdir` or absolute paths)

---

## Available Libraries (confirmed in environment)

| Library | Use For |
|---------|---------|
| `email` (stdlib) | MIME email parsing and creation |
| `icalendar` | iCalendar (.ics) parsing and creation |
| `openpyxl` | XLSX spreadsheet reading/writing |
| `pypdf` | PDF text extraction |
| `python-docx` (`docx`) | DOCX creation and modification |
| `reportlab` | PDF creation from scratch |
| `Pillow` (`PIL`) | Image creation and manipulation |
| `json` (stdlib) | JSON output |
| `csv` (stdlib) | CSV parsing/writing |
| `lxml` | XML/HTML parsing if needed |
| `chardet` | Character encoding detection |
| `python-dateutil` | Date parsing and manipulation |
