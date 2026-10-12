---
name: office-workflow
description: >
  General skill for office-workflow automation tasks that read, filter, transform,
  and produce office artifacts (MIME email, iCalendar, XLSX, PDF, DOCX, images, JSON, CSV, TXT).
  Covers MIME-aware parsing, subject/recipient/date/content filtering, format conversion,
  quantitative analysis, scheduling, summarization, routing, and preservation constraints.
  All solutions are implemented as solve.py with a callable run() function.
---

# Office Workflow Automation Skill

## 1. Task Pattern

Every task in this family follows the same structural contract:

- **Input**: A natural-language instruction describing what office artifacts to read, how to filter/transform them, and what output to produce.
- **Code artifact**: Write `/app/solve.py` containing a `run()` function that performs all operations.
- **Test contract**: Tests invoke `from solve import run; run()` and verify outputs.
- **Working directory**: `/app` is the CWD; data lives under `/app/data/`.
- **All imports** must be at the top of `solve.py` (or inside `run()`).

### Solving Strategy

1. **Parse the instruction** to identify:
   - Source artifacts: which files, what format, where located
   - Filtering criteria: subject match, recipient match, date range, content keywords, row conditions
   - Transformation: extraction, summarization, scheduling, quantitative analysis, format conversion
   - Destination artifacts: output file format(s), path(s), and structure
   - Constraints: preservation of existing content, consistency across outputs, routing rules
2. **Implement `run()`** using the appropriate library recipes below.
3. **Test** by running `python3 solve.py` and inspecting outputs.

## 2. Available Libraries

| Purpose | Library | Import |
|---------|---------|--------|
| MIME email parsing | stdlib email | `import email; from email import policy` |
| MIME email creation | stdlib email | `from email.message import EmailMessage` |
| iCalendar parse/create | icalendar | `from icalendar import Calendar, Event` |
| XLSX read/write | openpyxl | `import openpyxl` |
| PDF reading | pypdf | `from pypdf import PdfReader` |
| PDF generation | reportlab | `from reportlab.pdfgen import canvas` |
| DOCX read/write | python-docx | `from docx import Document` |
| Image creation | Pillow | `from PIL import Image, ImageDraw` |
| HTML/XML parsing | lxml | `from lxml import etree` |
| JSON | stdlib | `import json` |
| CSV | stdlib | `import csv` |
| Regex | stdlib | `import re` |
| Dates/times | stdlib | `from datetime import datetime, timedelta, date` |
| File paths | stdlib | `from pathlib import Path` |

## 3. Artifact Parsing Recipes

### 3.1 MIME Email (.eml)

**Reading:**
```python
from email import policy
from pathlib import Path
import email

def parse_eml(path):
    """Parse an .eml file and return (headers_dict, plain_text_body)."""
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    
    headers = {}
    for key in msg.keys():
        headers[key] = msg[key]
    
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_content()
                if isinstance(payload, str):
                    body = payload
                break
    else:
        payload = msg.get_content()
        if isinstance(payload, str):
            body = payload
    
    return headers, body
```

**Key points:**
- Always use `policy=policy.default` for modern API (`.get_content()` works properly).
- Use `message_from_binary_file` with `"rb"` mode for reliable parsing.
- `msg["Subject"]` returns the decoded subject string.
- For multipart messages, walk parts and find `text/plain` content type.
- Subject comparison should be exact string match unless the task says otherwise.
- Body text from `get_content()` may have trailing whitespace; strip if the task requires it.

**Creating .eml:**
```python
from email.message import EmailMessage
from email import policy

msg = EmailMessage(policy=policy.default)
msg["From"] = "sender@example.com"
msg["To"] = "recipient@example.com"
msg["Subject"] = "Subject Line"
msg.set_content("Body text here")

with open("output.eml", "w") as f:
    f.write(msg.as_string())
```

### 3.2 iCalendar (.ics)

**Reading:**
```python
from icalendar import Calendar
from datetime import datetime, date

def normalize_dt(val):
    """Convert icalendar .dt to datetime.datetime regardless of source type.
    
    iCalendar DTSTART can be either DATE (all-day events) or DATETIME (timed events).
    Python cannot compare date and datetime objects, so we normalize to datetime.
    All-day events become midnight naive datetime.
    """
    if val is None:
        return None
    dt = val.dt if hasattr(val, 'dt') else val
    if isinstance(dt, datetime):
        return dt
    if isinstance(dt, date):
        return datetime(dt.year, dt.month, dt.day)  # midnight, naive
    return dt

def parse_ics(path):
    """Parse an .ics file and return list of event dicts."""
    with open(path, "rb") as f:
        cal = Calendar.from_ical(f.read())
    
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            event = {
                "summary": str(component.get("summary", "")),
                "dtstart": normalize_dt(component.get("dtstart")),
                "dtend": normalize_dt(component.get("dtend")),
                "uid": str(component.get("uid", "")),
                "location": str(component.get("location", "")),
                "description": str(component.get("description", "")),
            }
            events.append(event)
    return events
```

**Creating:**
```python
from icalendar import Calendar, Event
from datetime import datetime
import uuid

cal = Calendar()
cal.add("prodid", "-//My Product//EN")
cal.add("version", "2.0")

event = Event()
event.add("summary", "Meeting Title")
event.add("dtstart", datetime(2024, 1, 15, 10, 0, 0))
event.add("dtend", datetime(2024, 1, 15, 11, 0, 0))
event["uid"] = str(uuid.uuid4())
cal.add_component(event)

with open("output.ics", "wb") as f:
    f.write(cal.to_ical())
```

**Updating existing .ics (preservation with duplicate detection):**
```python
def add_events_preserving(calendar_path, new_events):
    """Add events to existing calendar, skipping duplicates by UID."""
    with open(calendar_path, "rb") as f:
        cal = Calendar.from_ical(f.read())
    
    # Collect existing UIDs to avoid duplicates
    existing_uids = set()
    for component in cal.walk():
        if component.name == "VEVENT":
            uid = str(component.get("uid", ""))
            if uid:
                existing_uids.add(uid)
    
    # Add only non-duplicate events
    for event in new_events:
        uid = str(event.get("uid", ""))
        if uid not in existing_uids:
            cal.add_component(event)
    
    with open(calendar_path, "wb") as f:
        f.write(cal.to_ical())
```

### 3.3 XLSX Spreadsheets

**Reading:**
```python
import openpyxl

def read_xlsx(path):
    """Read all rows from first sheet as list of dicts (header-keyed)."""
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    return [dict(zip(headers, row)) for row in rows[1:]]
```

**Writing:**
```python
import openpyxl

def write_xlsx(path, headers, rows):
    """Write headers + rows to an XLSX file."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
```

### 3.4 PDF Reading

```python
from pypdf import PdfReader

def read_pdf_text(path):
    """Extract all text from a PDF."""
    reader = PdfReader(path)
    text_parts = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)
```

### 3.5 PDF Generation

```python
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

def create_pdf(path, lines):
    """Create a simple PDF with text lines."""
    c = canvas.Canvas(path, pagesize=letter)
    y = 750
    for line in lines:
        c.drawString(72, y, line)
        y -= 20
        if y < 72:
            c.showPage()
            y = 750
    c.save()
```

### 3.6 DOCX

**Reading:**
```python
from docx import Document

def read_docx(path):
    """Read all paragraph text from a DOCX file."""
    doc = Document(path)
    return [p.text for p in doc.paragraphs]
```

**Writing:**
```python
from docx import Document

def write_docx(path, paragraphs):
    """Create a DOCX with given paragraphs."""
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(path)
```

### 3.7 Image (JPEG/PNG) Generation

```python
from PIL import Image, ImageDraw

def create_text_image(path, text_lines, width=800, height=600):
    """Create an image with text lines."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 20
    for line in text_lines:
        draw.text((20, y), line, fill="black")
        y += 25
    img.save(path)
```

### 3.8 JSON

```python
import json

# Read
with open("data.json") as f:
    data = json.load(f)

# Write
with open("output.json", "w") as f:
    json.dump(data, f, indent=2)
```

## 4. Common Workflow Patterns

### 4.1 Relevance Filtering (email → text)

Select messages matching criteria (subject, sender, recipient), extract content, write consolidated output.

```python
def run():
    source_dir = Path("data/emails/<Recipient>")
    target_subjects = {"subject1", "subject2"}
    
    selected = []
    for eml_path in sorted(source_dir.glob("*.eml")):
        headers, body = parse_eml(eml_path)
        if headers.get("Subject") in target_subjects:
            selected.append((eml_path.name, headers, body.strip()))
    
    selected.sort(key=lambda x: x[0])
    
    blocks = []
    for fname, headers, body in selected:
        blocks.append(f"Subject: {headers['Subject']}\n{body}")
    
    with open("data/answer.txt", "w") as f:
        f.write("\n\n".join(blocks) + "\n")
```

### 4.2 Calendar Extraction (email → ICS)

Parse meeting details from emails, create calendar events.

```python
def run():
    # Parse emails for meeting info
    # Create ICS with extracted events
    # Preserve existing calendar events if updating
    pass
```

### 4.3 Table Extraction (PDF/XLSX → structured output)

Extract tables from documents, filter rows, produce summaries.

### 4.4 Quantitative Analysis (XLSX → image/text/JSON)

Read numeric data, compute statistics, generate charts or formatted reports.

### 4.5 Routing (one output per recipient/message)

```python
def run():
    # Group messages by recipient or other criterion
    # Write separate output files per group
    from collections import defaultdict
    groups = defaultdict(list)
    for msg in messages:
        groups[msg["recipient"]].append(msg)
    
    for recipient, msgs in groups.items():
        output_path = Path(f"data/output/{recipient}.txt")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            # Write recipient-specific content
            pass
```

### 4.6 Format Conversion

Convert between formats while preserving content:
- Email → DOCX report
- XLSX → PDF table
- ICS → TXT schedule
- etc.

### 4.7 Scheduling (find common free time)

```python
from datetime import datetime, timedelta

def find_common_free_time(events_lists, duration_minutes=60,
                          window_start=None, window_end=None):
    """
    Find the earliest available time slot across multiple calendars.
    
    events_lists: list of lists of event dicts (one per calendar).
                  Each event has 'dtstart' and 'dtend' as datetime.
    duration_minutes: required slot duration in minutes.
    window_start, window_end: optional time window to search within.
    
    Returns the earliest (start, end) tuple that fits, or None.
    """
    # Step 1: Collect all busy intervals from all calendars
    busy = []
    for events in events_lists:
        for e in events:
            if e["dtstart"] and e["dtend"]:
                busy.append((e["dtstart"], e["dtend"]))
    
    if not busy:
        # No events at all — first available slot is window_start
        if window_start and window_end:
            return (window_start, window_start + timedelta(minutes=duration_minutes))
        return None
    
    # Step 2: Sort by start time, then merge overlapping intervals
    # Critical: unmerged overlaps create false conflicts
    busy.sort(key=lambda x: x[0])
    merged = [busy[0]]
    for start, end in busy[1:]:
        if start <= merged[-1][1]:  # overlaps with last merged interval
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    
    # Step 3: Scan gaps between merged intervals
    duration = timedelta(minutes=duration_minutes)
    
    # Gap before first event
    if window_start and merged[0][0] - window_start >= duration:
        return (window_start, window_start + duration)
    
    # Gaps between events
    for i in range(len(merged) - 1):
        gap_start = merged[i][1]
        gap_end = merged[i + 1][0]
        if gap_end - gap_start >= duration:
            return (gap_start, gap_start + duration)
    
    # Gap after last event
    if window_end and window_end - merged[-1][1] >= duration:
        return (merged[-1][1], merged[-1][1] + duration)
    
    return None  # No slot found
```

## 5. Preservation and Consistency Rules

1. **Never modify source files** unless the task explicitly says to update in place (e.g., adding events to an existing calendar).
2. **When updating in place**, read the full existing content, append/modify, then write back — never overwrite with only new content.
3. **Cross-output consistency**: If the same fact appears in multiple outputs (e.g., a date in both a TXT and an ICS), ensure the values are identical.
4. **Strip vs. preserve whitespace**: Follow the task instruction precisely. If it says "stripped plain-text body", use `.strip()`. If it says "complete body", preserve as-is.
5. **File endings**: Pay attention to trailing newline requirements. "End with one newline" means the file's last byte is `\n` but not `\n\n`.

## 6. Output Formatting Rules

### TXT blocks format
```
Subject: <subject>
<body text>

Subject: <subject>
<body text>
```
- Adjacent blocks separated by exactly one blank line
- File ends with exactly one newline

### General principles
- Read the instruction's format specification literally
- "One blank line" between blocks = `\n\n`
- "End with one newline" = file content + `\n` at the very end
- Sort order: by filename unless otherwise specified

## 7. Error Handling and Edge Cases

- **Empty results**: If no messages match, write an empty file (or file with just a newline, depending on spec).
- **Encoding**: Use `"rb"` for reading emails; use UTF-8 for text outputs unless specified otherwise.
- **Multipart emails**: Always walk parts to find text/plain; don't assume single-part structure.
- **Subject decoding**: `policy.default` handles RFC 2047 encoded words automatically.
- **iCalendar date/datetime duality**: `DTSTART;VALUE=DATE:20240115` produces a `date` object (all-day event), while `DTSTART:20240115T100000` produces a `datetime` object (timed event). Python 3 cannot compare `date` and `datetime` directly — sorting mixed types raises `TypeError`. Always use `normalize_dt()` to convert everything to `datetime` before comparison or sorting.
- **File paths**: Use `Path` objects and `mkdir(parents=True, exist_ok=True)` for output directories.

## 8. Implementation Checklist

Before finalizing solve.py:

- [ ] `run()` function is defined and callable
- [ ] All imports are present
- [ ] Source files are read from correct paths
- [ ] Filtering criteria match instruction exactly (exact string match vs. substring vs. regex)
- [ ] Output format matches instruction (block structure, separators, trailing newline)
- [ ] Sort order is correct (by filename, by date, etc.)
- [ ] Existing content is preserved where required
- [ ] Cross-output facts are consistent
- [ ] Tested by running `python3 solve.py` and inspecting output
