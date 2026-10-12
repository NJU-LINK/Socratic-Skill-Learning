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
   - Filtering criteria: subject match, recipient match, date range, content keywords, row conditions, class membership
   - Transformation: extraction, summarization, scheduling, quantitative analysis, format conversion
   - Destination artifacts: output file format(s), path(s), and structure
   - Constraints: preservation of existing content, consistency across outputs, routing rules, deduplication requirements
   - **Multi-source reconciliation**: If multiple source files exist, determine how to combine/reconcile them (union, intersection, join on key, etc.)

2. **Identify the workflow pattern** from Section 4 that best matches the task:
   - Single-source filtering → 4.1 (Relevance Filtering)
   - Email → Calendar → 4.2 (Calendar Extraction)
   - Table extraction/filtering → 4.3 (Table Extraction)
   - Statistics/charts → 4.4 (Quantitative Analysis)
   - Per-recipient output → 4.5 (Routing)
   - Format conversion → 4.6 (Format Conversion)
   - Scheduling → 4.7 (Scheduling)
   - Multi-source summary → 4.8 (Summarization)
   - Multiple sources to reconcile → 4.9 (Multi-Source Reconciliation)

3. **Implement `run()`** using the appropriate library recipes and patterns.

4. **Test** by running `python3 solve.py` and inspecting outputs.

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
| Date parsing (natural language) | python-dateutil | `from dateutil.parser import parse` |
| Relative date math | python-dateutil | `from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR` |
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
- **Nested multipart**: `walk()` visits parts depth-first. The first `text/plain` is typically the main body (from multipart/alternative). Subsequent `text/plain` parts are usually attachments. For most tasks, breaking on the first `text/plain` is correct.
- Subject comparison should be exact string match unless the task says otherwise.
- Body text from `get_content()` includes all content in the text/plain part (including "Sent at:" lines). `.strip()` only removes leading/trailing whitespace, not internal lines.

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
    """Convert icalendar .dt to naive datetime.datetime for comparison.
    
    iCalendar DTSTART can be:
    - DATE (all-day events): DTSTART;VALUE=DATE:20240115 → date object
    - DATETIME naive (timed events): DTSTART:20240115T100000 → naive datetime
    - DATETIME with timezone: DTSTART;TZID=America/New_York:20240115T100000 → aware datetime
    
    Python cannot compare date/datetime or naive/aware types, so we normalize everything
    to naive datetime. Timezone-aware datetimes are converted to UTC then stripped of tzinfo.
    All-day events become midnight naive datetime.
    """
    if val is None:
        return None
    dt = val.dt if hasattr(val, 'dt') else val
    if isinstance(dt, datetime):
        # If timezone-aware, convert to UTC and strip tzinfo for comparison
        if dt.tzinfo is not None:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
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

### 3.9 CSV

```python
import csv

# Read
with open("data.csv", "r", newline="") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# Write
with open("output.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["Name", "Score", "Grade"])
    writer.writeheader()
    writer.writerows(rows)
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

**Advanced filtering patterns:**

**Class membership filtering** (e.g., filter by domain, category, or pattern):
```python
# Filter emails by sender domain
for eml_path in sorted(source_dir.glob("*.eml")):
    headers, body = parse_eml(eml_path)
    sender = headers.get("From", "")
    if "@gmail.com" in sender:  # Domain-based filtering
        selected.append(...)

# Filter by subject pattern (regex)
import re
pattern = re.compile(r"^(meeting|scheduled|approved)", re.IGNORECASE)
for eml_path in sorted(source_dir.glob("*.eml")):
    headers, body = parse_eml(eml_path)
    subject = headers.get("Subject", "")
    if pattern.match(subject):
        selected.append(...)

# Filter by date range
from datetime import datetime
from email.utils import parsedate_to_datetime
for eml_path in sorted(source_dir.glob("*.eml")):
    headers, body = parse_eml(eml_path)
    date_str = headers.get("Date", "")
    if date_str:
        msg_date = parsedate_to_datetime(date_str)
        if datetime(2024, 1, 1) <= msg_date <= datetime(2024, 12, 31):
            selected.append(...)
```

### 4.2 Calendar Extraction (email → ICS)

Parse meeting details from email bodies and create calendar events.

```python
from dateutil.parser import parse as parse_date
from datetime import datetime, timedelta
from icalendar import Calendar, Event
import uuid

def extract_meeting_from_email(subject, body):
    """Extract meeting info from email body. Returns event dict or None."""
    # Strategy: try to parse the entire body for a date
    # fuzzy=True ignores non-date text and extracts the first date found
    try:
        dtstart = parse_date(body, fuzzy=True)
    except (ValueError, OverflowError):
        return None  # No date found
    
    # Default 1-hour meeting
    dtend = dtstart + timedelta(hours=1)
    
    return {
        "summary": subject,
        "dtstart": dtstart,
        "dtend": dtend,
        "description": body[:200],
    }

def run():
    source_dir = Path("data/emails/Bob")
    output_ics = Path("data/calendar.ics")
    
    cal = Calendar()
    cal.add("prodid", "-//Office Workflow//EN")
    cal.add("version", "2.0")
    
    for eml_path in sorted(source_dir.glob("*.eml")):
        headers, body = parse_eml(eml_path)
        subject = headers.get("Subject", "")
        
        # Filter for meeting-related emails
        if "meeting" in subject.lower():
            meeting = extract_meeting_from_email(subject, body.strip())
            if meeting:
                event = Event()
                event.add("summary", meeting["summary"])
                event.add("dtstart", meeting["dtstart"])
                event.add("dtend", meeting["dtend"])
                event.add("description", meeting["description"])
                event["uid"] = str(uuid.uuid4())
                cal.add_component(event)
    
    with open(output_ics, "wb") as f:
        f.write(cal.to_ical())
```

**Alternative: Line-by-line date extraction**

If the task requires extracting dates from specific lines (not the whole body), split the body and try each line:

```python
def extract_date_from_lines(body):
    """Try to parse a date from each line of the body."""
    for line in body.split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            return parse_date(line, fuzzy=True)
        except (ValueError, OverflowError):
            continue
    return None
```

### 4.3 Table Extraction (PDF/XLSX → structured output)

Extract tables from documents, filter rows, produce summaries.

```python
def run():
    # Example: Extract rows from XLSX where score > 80
    xlsx_path = Path("data/scores.xlsx")
    rows = read_xlsx(xlsx_path)
    
    # Filter rows
    high_scores = [r for r in rows if r.get("Score", 0) > 80]
    
    # Write filtered results
    output_path = Path("data/high_scores.json")
    with open(output_path, "w") as f:
        json.dump(high_scores, f, indent=2)
    
    # Or write as CSV
    if high_scores:
        csv_path = Path("data/high_scores.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=high_scores[0].keys())
            writer.writeheader()
            writer.writerows(high_scores)
```

### 4.4 Quantitative Analysis (XLSX → image/text/JSON)

Read numeric data, compute statistics, generate charts or formatted reports.

```python
from PIL import Image, ImageDraw

def create_bar_chart(data_dict, output_path, title="Chart"):
    """Create a simple bar chart image from {label: value} dict."""
    width, height = 400, 300
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    if not data_dict:
        img.save(output_path)
        return
    
    bar_width = 60
    gap = 20
    x_start = 50
    max_val = max(data_dict.values())
    chart_height = 200
    y_base = 250
    
    for i, (name, val) in enumerate(data_dict.items()):
        x = x_start + i * (bar_width + gap)
        bar_height = int((val / max_val) * chart_height) if max_val > 0 else 0
        y = y_base - bar_height
        draw.rectangle([x, y, x + bar_width, y_base], fill="steelblue", outline="black")
        draw.text((x + 10, y_base + 5), str(name), fill="black")
        draw.text((x + 15, y - 15), str(val), fill="black")
    
    draw.text((150, 10), title, fill="black")
    img.save(output_path)

def run():
    # Example: Read scores, compute stats, generate chart
    xlsx_path = Path("data/scores.xlsx")
    rows = read_xlsx(xlsx_path)
    
    # Extract scores
    scores = {r["Name"]: r["Score"] for r in rows if "Score" in r}
    
    # Compute statistics
    if scores:
        values = list(scores.values())
        stats = {
            "count": len(values),
            "mean": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
        }
        
        # Write stats as JSON
        with open("data/stats.json", "w") as f:
            json.dump(stats, f, indent=2)
        
        # Generate bar chart
        create_bar_chart(scores, "data/chart.png", title="Student Scores")
```

### 4.5 Routing (one output per recipient/message)

```python
from collections import defaultdict

def run():
    # Example: Group emails by recipient, write separate output files
    source_dir = Path("data/emails")
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Group by recipient (from To: header)
    groups = defaultdict(list)
    for eml_path in sorted(source_dir.glob("*.eml")):
        headers, body = parse_eml(eml_path)
        recipient = headers.get("To", "unknown")
        groups[recipient].append({
            "filename": eml_path.name,
            "subject": headers.get("Subject", ""),
            "body": body.strip(),
        })
    
    # Write one file per recipient
    for recipient, messages in groups.items():
        # Sanitize recipient name for filename
        safe_name = re.sub(r'[^\w\-.]', '_', recipient)
        output_path = output_dir / f"{safe_name}.txt"
        
        blocks = []
        for msg in messages:
            blocks.append(f"Subject: {msg['subject']}\n{msg['body']}")
        
        with open(output_path, "w") as f:
            f.write("\n\n".join(blocks) + "\n")
```

### 4.6 Format Conversion

Convert between formats while preserving content.

**Email → DOCX:**
```python
from docx import Document

def run():
    source_dir = Path("data/emails/Bob")
    output_docx = Path("data/report.docx")
    
    doc = Document()
    doc.add_heading("Email Report", 0)
    
    for eml_path in sorted(source_dir.glob("*.eml")):
        headers, body = parse_eml(eml_path)
        
        doc.add_heading(headers.get("Subject", "No Subject"), level=1)
        doc.add_paragraph(f"From: {headers.get('From', 'Unknown')}")
        doc.add_paragraph(f"To: {headers.get('To', 'Unknown')}")
        doc.add_paragraph("")  # Blank line
        doc.add_paragraph(body.strip())
        doc.add_paragraph("")  # Separator
    
    doc.save(output_docx)
```

**XLSX → PDF table:**
```python
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

def run():
    xlsx_path = Path("data/scores.xlsx")
    output_pdf = Path("data/report.pdf")
    
    rows = read_xlsx(xlsx_path)
    
    c = canvas.Canvas(output_pdf, pagesize=letter)
    y = 750
    
    # Header
    if rows:
        headers = list(rows[0].keys())
        c.setFont("Helvetica-Bold", 12)
        x = 72
        for header in headers:
            c.drawString(x, y, str(header))
            x += 100
        y -= 20
    
    # Data rows
    c.setFont("Helvetica", 10)
    for row in rows:
        x = 72
        for key in headers:
            c.drawString(x, y, str(row.get(key, "")))
            x += 100
        y -= 15
        if y < 72:
            c.showPage()
            y = 750
    
    c.save()
```

### 4.7 Scheduling (find common free time)

```python
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta, MO

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

**Computing window boundaries with relativedelta:**

When the task specifies relative time windows (e.g., "next week", "next 7 days"), use `relativedelta`:

```python
from dateutil.relativedelta import relativedelta, MO

# "Search the next 7 days"
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
window_start = today
window_end = today + relativedelta(days=7)

# "Find a slot next week" (Monday to Sunday)
next_monday = today + relativedelta(weekday=MO(+1))
window_start = next_monday
window_end = next_monday + relativedelta(days=7)

# "Find a slot this month"
window_start = today.replace(day=1)
window_end = window_start + relativedelta(months=1)
```

### 4.8 Summarization

Summarize content from multiple sources into a consolidated output.

```python
def run():
    # Example: Summarize all emails from a directory
    source_dir = Path("data/emails/Bob")
    output_path = Path("data/summary.txt")
    
    summaries = []
    for eml_path in sorted(source_dir.glob("*.eml")):
        headers, body = parse_eml(eml_path)
        subject = headers.get("Subject", "No Subject")
        sender = headers.get("From", "Unknown")
        
        # Extract first sentence or first N chars as summary
        body_stripped = body.strip()
        first_sentence = body_stripped.split('.')[0] + '.' if '.' in body_stripped else body_stripped[:100]
        
        summaries.append({
            "subject": subject,
            "from": sender,
            "preview": first_sentence,
        })
    
    # Write summary
    with open(output_path, "w") as f:
        f.write("Email Summary\n")
        f.write("=" * 50 + "\n\n")
        
        for s in summaries:
            f.write(f"Subject: {s['subject']}\n")
            f.write(f"From: {s['from']}\n")
            f.write(f"Preview: {s['preview']}\n")
            f.write("\n")
```

### 4.9 Multi-Source Reconciliation

When tasks involve multiple source files that must be combined or reconciled.

**Pattern: Union of multiple email directories**

```python
def run():
    # Combine emails from multiple recipients
    source_dirs = [Path("data/emails/Alice"), Path("data/emails/Bob")]
    all_emails = []
    
    for source_dir in source_dirs:
        if source_dir.exists():
            for eml_path in sorted(source_dir.glob("*.eml")):
                headers, body = parse_eml(eml_path)
                all_emails.append({
                    "source": eml_path.name,
                    "directory": source_dir.name,
                    "subject": headers.get("Subject", ""),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "body": body.strip(),
                })
    
    # Sort by source filename
    all_emails.sort(key=lambda x: x["source"])
    
    # Write combined output
    output_path = Path("data/combined.txt")
    blocks = []
    for email in all_emails:
        blocks.append(f"Subject: {email['subject']}\nFrom: {email['from']}\n{email['body']}")
    
    with open(output_path, "w") as f:
        f.write("\n\n".join(blocks) + "\n")
```

**Pattern: Deduplication across sources**

```python
def run():
    # Remove duplicate emails (by Subject+From+Body hash)
    source_dirs = [Path("data/emails/Alice"), Path("data/emails/Bob")]
    seen = set()
    unique_emails = []
    
    for source_dir in source_dirs:
        if source_dir.exists():
            for eml_path in sorted(source_dir.glob("*.eml")):
                headers, body = parse_eml(eml_path)
                # Create a hash key from subject, from, and body
                key = (headers.get("Subject", ""), headers.get("From", ""), body.strip())
                if key not in seen:
                    seen.add(key)
                    unique_emails.append({
                        "source": eml_path.name,
                        "subject": headers.get("Subject", ""),
                        "body": body.strip(),
                    })
    
    # Write deduplicated output
    output_path = Path("data/unique.txt")
    blocks = []
    for email in unique_emails:
        blocks.append(f"Subject: {email['subject']}\n{email['body']}")
    
    with open(output_path, "w") as f:
        f.write("\n\n".join(blocks) + "\n")
```

**Pattern: Join email data with spreadsheet data**

```python
def run():
    # Example: Match emails to student records by email address
    email_dir = Path("data/emails")
    xlsx_path = Path("data/students.xlsx")
    
    # Load student records
    students = read_xlsx(xlsx_path)
    email_to_student = {s["Email"]: s for s in students}
    
    # Process emails and enrich with student data
    enriched = []
    for eml_path in sorted(email_dir.glob("*.eml")):
        headers, body = parse_eml(eml_path)
        sender_email = headers.get("From", "")
        
        # Look up student by email
        student = email_to_student.get(sender_email)
        if student:
            enriched.append({
                "name": student["Name"],
                "subject": headers.get("Subject", ""),
                "body": body.strip(),
                "grade": student.get("Grade", ""),
            })
    
    # Write enriched output
    output_path = Path("data/enriched.json")
    with open(output_path, "w") as f:
        json.dump(enriched, f, indent=2)
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
- **iCalendar date/datetime duality**: `DTSTART;VALUE=DATE:20240115` produces a `date` object (all-day event), while `DTSTART:20240115T100000` produces a naive `datetime` object (timed event), and `DTSTART;TZID=...:20240115T100000` produces a timezone-aware `datetime`. Python 3 cannot compare `date`/`datetime` or naive/aware types — sorting mixed types raises `TypeError`. Always use `normalize_dt()` to convert everything to naive `datetime` before comparison or sorting.
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
