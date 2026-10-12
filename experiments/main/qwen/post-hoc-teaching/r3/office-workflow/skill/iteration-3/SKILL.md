---
name: office-workflow
description: >
  General skill for office automation workflows that read, filter, transform,
  and route between office artifacts (MIME email, iCalendar, XLSX, PDF, DOCX, CSV)
  producing outputs (TXT, ICS, JPEG, DOCX, EML, PDF, JSON, CSV). Handles MIME-aware
  parsing, subject/content filtering, table extraction, quantitative analysis,
  scheduling with free-time computation, summarization, notification, email
  attachment extraction, and recipient-based routing with format conversion.
  Supports cross-artifact reconciliation, in-place calendar updates, and
  cross-output consistency.
---

# Office Workflow Skill

## Overview

This skill handles a family of office automation tasks where the agent must:
1. **Read** one or more source office artifacts (email, calendar, spreadsheet, PDF, CSV)
2. **Process** them according to a specified workflow relation (filtering, extraction, scheduling, summarization, routing, quantitative analysis, attachment processing)
3. **Write** destination artifacts in the required format
4. **Preserve** source content integrity and ensure consistency across outputs

The solution is always a Python script at `/app/solve.py` exposing a callable `run()` function. Tests invoke `from solve import run; run()`.

## Environment & Available Libraries

### Confirmed available (stdlib + installed):
- `email` — MIME email parsing and construction
- `openpyxl` — XLSX read/write
- `icalendar` — iCalendar read/write
- `python-docx` (`import docx`) — DOCX read/write
- `reportlab` — PDF generation
- `PIL` / `Pillow` — Image creation (JPEG, PNG)
- `csv`, `json`, `re`, `datetime`, `os`, `glob`, `pathlib` — stdlib utilities
- `zipfile` — ZIP archive handling
- `struct` — Binary data handling

### NOT available (do not import):
- `pandas`, `matplotlib`, `PyPDF2`, `pdfplumber`, `fitz` (PyMuPDF), `pdfminer`

**PDF limitation:** `reportlab` can **generate** PDFs (write text, draw shapes, create tables) but **cannot read/extract text from existing PDFs**. PDFs are not ZIP archives — `zipfile` cannot extract PDF content. Without PyPDF2, pdfplumber, PyMuPDF, or pdfminer, **PDF text extraction is not feasible** in this environment. If a task requires reading PDFs, note this as an environment limitation.

## Core Patterns

### Pattern 1: MIME Email Parsing

```python
import email
import os
import glob
import re
from email.header import decode_header, make_header

def get_decoded_header(msg, header_name, default=""):
    """Decode an RFC 2047 encoded header to a plain string.
    
    Real-world emails frequently use MIME encoding for non-ASCII characters:
    - '=?iso-8859-1?Q?M=F6te_p=E5_morgon?=' -> 'Möte på morgon'
    - '=?utf-8?b?U2NoZWR1bGVkIE1lZXRpbmc=?=' -> 'Scheduled Meeting'
    - '=?utf-8?Q?Re=3A_Application_?= =?utf-8?Q?Approved?=' -> 'Re: Application Approved'
    
    Always use this for header comparison (Subject, From, To) and extraction.
    """
    raw = msg.get(header_name)
    if raw is None:
        return default
    decoded_parts = decode_header(raw)
    return str(make_header(decoded_parts))

def parse_eml_directory(directory, subject_filter=None):
    """Parse all .eml files in a directory, optionally filtering by subject."""
    eml_files = sorted(glob.glob(os.path.join(directory, "*.eml")))
    results = []
    for fpath in eml_files:
        with open(fpath, "rb") as f:
            msg = email.message_from_binary_file(f)
        
        # CRITICAL: Decode RFC 2047 headers before comparison
        subject = get_decoded_header(msg, "Subject", "")
        if subject_filter and subject not in subject_filter:
            continue
        
        # Extract plain text body from multipart or single-part
        body = extract_plain_body(msg)
        results.append({
            "filename": os.path.basename(fpath),
            "subject": subject,
            "from": get_decoded_header(msg, "From", ""),
            "to": get_decoded_header(msg, "To", ""),
            "date": get_decoded_header(msg, "Date", ""),
            "body": body,
            "message": msg,
        })
    return results

def extract_plain_body(msg):
    """Extract text body from MIME message, with HTML fallback.
    
    Prefers text/plain when available. Falls back to HTML tag stripping
    for HTML-only emails (common in real-world messages).
    """
    if msg.is_multipart():
        plain_text = None
        html_text = None
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and plain_text is None:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                plain_text = payload.decode(charset)
            elif ct == "text/html" and html_text is None:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                html_text = payload.decode(charset)
        if plain_text is not None:
            return plain_text
        if html_text is not None:
            # Strip HTML tags and decode basic entities for plain text
            text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
            text = text.replace('&lt;', '<').replace('&gt;', '>')
            return text
        return ""
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        if payload:
            decoded = payload.decode(charset)
            if msg.get_content_type() == "text/html":
                text = re.sub(r'<br\s*/?>', '\n', decoded, flags=re.IGNORECASE)
                text = re.sub(r'<[^>]+>', '', text)
                text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
                text = text.replace('&lt;', '<').replace('&gt;', '>')
                return text
            return decoded
        return ""

from email.utils import getaddresses

def extract_recipients(msg):
    """Extract all recipient email addresses from To, Cc, Bcc headers.
    
    Uses email.utils.getaddresses to correctly parse RFC 2822 address formats:
    - 'john@example.com'
    - '"John Doe" <john@example.com>'
    - 'Alice <alice@a.com>, Bob <bob@b.com>'
    - Group syntax: 'group: a@a.com, b@b.com;'
    """
    recipients = []
    for header in ["To", "Cc", "Bcc"]:
        raw = msg.get(header)
        if raw is None:
            continue
        decoded = get_decoded_header(msg, header, "")
        # getaddresses handles "Name <addr>" format, multiple addresses, etc.
        for name, addr in getaddresses([decoded]):
            if addr:
                recipients.append(addr)
    return recipients
```

**Key details:**
- Always open `.eml` files in binary mode (`"rb"`) and use `message_from_binary_file`
- **CRITICAL: Use `get_decoded_header()` for all header access** — `msg.get("Subject")` returns raw RFC 2047 encoded strings that will fail exact-match filters
- Subject filtering is exact match on the **decoded** subject
- `get_payload(decode=True)` handles Content-Transfer-Encoding automatically
- Sort results by filename when the task requires ordering
- "Stripped" body means `.strip()` to remove leading/trailing whitespace
- HTML-only emails are handled via tag stripping fallback

### Pattern 2: Email Construction (EML output)

```python
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

def create_eml(from_addr, to_addr, subject, body, attachments=None):
    """Create a MIME email message."""
    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain"))
        for fname, data in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={fname}")
            msg.attach(part)
    else:
        msg = MIMEText(body, "plain")
    
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    return msg
```

### Pattern 3: iCalendar Processing

```python
from icalendar import Calendar, Event
from datetime import datetime, timedelta, date

def normalize_to_datetime(dt_value):
    """Convert icalendar .dt values to naive datetime objects.
    
    icalendar returns either:
    - datetime.date (for all-day events: DTSTART;VALUE=DATE:20240325)
    - datetime.datetime (for timed events: DTSTART:20240325T090000Z)
    - timezone-aware datetime (for UTC events: DTSTART:20240325T090000Z)
    
    This function normalizes all to naive datetime for safe comparison.
    Strips timezone info to avoid TypeError when comparing with user-created datetimes.
    """
    if isinstance(dt_value, datetime):
        return dt_value.replace(tzinfo=None)  # strip timezone
    elif isinstance(dt_value, date):
        return datetime(dt_value.year, dt_value.month, dt_value.day)
    raise TypeError(f"Unexpected dt type from icalendar: {type(dt_value)}")

def parse_ics(filepath):
    """Parse an ICS file and return events."""
    with open(filepath, "rb") as f:
        cal = Calendar.from_ical(f.read())
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            events.append({
                "summary": str(component.get("summary", "")),
                "dtstart": normalize_to_datetime(component.get("dtstart").dt),
                "dtend": normalize_to_datetime(component.get("dtend").dt) if component.get("dtend") else None,
                "location": str(component.get("location", "")),
                "description": str(component.get("description", "")),
                "component": component,
            })
    return events

def create_ics(events, cal_name="Calendar"):
    """Create an ICS calendar from event dicts."""
    cal = Calendar()
    cal.add("prodid", "-//Office Workflow//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    for ev in events:
        event = Event()
        event.add("summary", ev["summary"])
        event.add("dtstart", ev["dtstart"])
        if ev.get("dtend"):
            event.add("dtend", ev["dtend"])
        if ev.get("location"):
            event.add("location", ev["location"])
        cal.add_component(event)
    return cal.to_ical()

def update_ics_inplace(filepath, new_events):
    """Add new events to an existing ICS file, preserving original events.
    
    Args:
        filepath: Path to existing ICS file
        new_events: List of event dicts to add
    """
    with open(filepath, "rb") as f:
        cal = Calendar.from_ical(f.read())
    
    for ev in new_events:
        event = Event()
        event.add("summary", ev["summary"])
        event.add("dtstart", ev["dtstart"])
        if ev.get("dtend"):
            event.add("dtend", ev["dtend"])
        if ev.get("location"):
            event.add("location", ev["location"])
        if ev.get("description"):
            event.add("description", ev["description"])
        cal.add_component(event)
    
    with open(filepath, "wb") as f:
        f.write(cal.to_ical())
```

### Pattern 4: XLSX Processing

```python
import openpyxl

def read_xlsx(filepath):
    """Read all sheets from an XLSX file."""
    wb = openpyxl.load_workbook(filepath)
    data = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
        data[sheet_name] = rows
    return data

def write_xlsx(filepath, sheets_data):
    """Write data to an XLSX file. sheets_data: {sheet_name: [[row], ...]}"""
    wb = openpyxl.Workbook()
    first = True
    for sheet_name, rows in sheets_data.items():
        if first:
            ws = wb.active
            ws.title = sheet_name
            first = False
        else:
            ws = wb.create_sheet(sheet_name)
        for row in rows:
            ws.append(row)
    wb.save(filepath)

def deduplicate_rows(rows, key_columns=None):
    """Remove duplicate rows from spreadsheet data.
    
    Args:
        rows: List of row tuples/lists (excluding header)
        key_columns: If provided, list of column indices to use as dedup key.
                     If None, uses entire row as key.
    
    Returns:
        List of unique rows (preserving first occurrence order)
    """
    seen = set()
    unique = []
    for row in rows:
        if key_columns is not None:
            key = tuple(row[i] for i in key_columns)
        else:
            key = tuple(row)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique
```

### Pattern 5: DOCX Processing

```python
import docx

def read_docx(filepath):
    """Read text content from a DOCX file."""
    doc = docx.Document(filepath)
    paragraphs = [p.text for p in doc.paragraphs]
    return paragraphs

def write_docx(filepath, paragraphs):
    """Write paragraphs to a DOCX file."""
    doc = docx.Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(filepath)
```

### Pattern 6: PDF Generation

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def write_pdf(filepath, lines, page_size=letter):
    """Write text lines to a simple PDF."""
    c = canvas.Canvas(filepath, pagesize=page_size)
    width, height = page_size
    y = height - 50
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
        if y < 50:
            c.showPage()
            y = height - 50
    c.save()
```

### Pattern 7: Image/Chart Generation

```python
from PIL import Image, ImageDraw, ImageFont

def create_text_image(filepath, text_lines, width=800, height=600):
    """Create a simple image with text."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 20
    for line in text_lines:
        draw.text((20, y), line, fill="black")
        y += 25
    img.save(filepath, "JPEG")

def create_bar_chart(filepath, labels, values, title="", width=600, height=400):
    """Create a simple bar chart image."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    if title:
        draw.text((width // 2 - len(title) * 4, 10), title, fill="black")
    
    max_val = max(values) if values else 1
    bar_width = (width - 80) // len(labels)
    chart_bottom = height - 40
    chart_height = chart_bottom - 60
    
    for i, (label, value) in enumerate(zip(labels, values)):
        x = 40 + i * bar_width
        bar_height = int((value / max_val) * chart_height)
        y = chart_bottom - bar_height
        draw.rectangle([x, y, x + bar_width - 5, chart_bottom], fill="steelblue")
        draw.text((x + 2, chart_bottom + 5), str(label), fill="black")
        draw.text((x + 2, y - 15), str(value), fill="black")
    
    img.save(filepath, "JPEG")
```

### Pattern 8: JSON Output

```python
import json

def write_json(filepath, data):
    """Write structured data as JSON."""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
```

### Pattern 9: Date Extraction from Text

```python
import re
from datetime import datetime

def extract_dates_from_text(text):
    """Extract dates from free-form text using common patterns.
    
    Handles:
    - "Month DD, YYYY" / "Month DD YYYY" (e.g., "October 1, 2022")
    - "DD/MM/YYYY" or "MM/DD/YYYY" (US format preferred)
    - "YYYY-MM-DD" (ISO format)
    - "Sent at: YYYY-MM-DD HH:MM:SS" (email timestamp format)
    
    Returns list of datetime objects found in the text.
    """
    dates = []
    
    months = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'may': 5, 'june': 6, 'july': 7, 'august': 8,
        'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
        'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9,
        'oct': 10, 'nov': 11, 'dec': 12
    }
    
    # Pattern 1: "Month DD, YYYY" or "Month DD YYYY"
    for m in re.finditer(r'\b(\w+)\s+(\d{1,2}),?\s+(\d{4})\b', text, re.IGNORECASE):
        month_name, day, year = m.group(1), int(m.group(2)), int(m.group(3))
        if month_name.lower() in months:
            try:
                dates.append(datetime(year, months[month_name.lower()], day))
            except ValueError:
                pass
    
    # Pattern 2: "DD/MM/YYYY" or "MM/DD/YYYY" (US format)
    for m in re.finditer(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', text):
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= a <= 12 and 1 <= b <= 31:
            try:
                dates.append(datetime(year, a, b))
            except ValueError:
                pass
    
    # Pattern 3: "YYYY-MM-DD"
    for m in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b', text):
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dates.append(datetime(year, month, day))
        except ValueError:
            pass
    
    # Pattern 4: "Sent at: YYYY-MM-DD HH:MM:SS"
    for m in re.finditer(r'Sent at:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', text):
        try:
            dates.append(datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            pass
    
    return dates
```

### Pattern 10: Temporal Computation — Free Time & Conflict Detection

This pattern is self-contained and includes `normalize_to_datetime`. If you also use Pattern 3, the function will be redefined (harmless).

```python
from datetime import datetime, timedelta, date

def normalize_to_datetime(dt_value):
    """Convert to naive datetime. See Pattern 3 for full documentation."""
    if isinstance(dt_value, datetime):
        return dt_value.replace(tzinfo=None)
    elif isinstance(dt_value, date):
        return datetime(dt_value.year, dt_value.month, dt_value.day)
    raise TypeError(f"Unexpected dt type: {type(dt_value)}")

def get_busy_intervals(cal_or_events):
    """Extract busy time intervals from an icalendar Calendar or list of events.
    
    Args:
        cal_or_events: Either a Calendar object or list of event dicts with
                       'dtstart' and 'dtend' keys.
    
    Returns:
        Sorted list of (start, end) naive datetime tuples.
    """
    intervals = []
    
    # Handle Calendar object
    if hasattr(cal_or_events, 'walk'):
        for component in cal_or_events.walk():
            if component.name == "VEVENT":
                start = normalize_to_datetime(component.get('dtstart').dt)
                end_dt = component.get('dtend')
                end = normalize_to_datetime(end_dt.dt) if end_dt else start
                intervals.append((start, end))
    else:
        # Handle list of event dicts (assume already normalized)
        for ev in cal_or_events:
            start = ev['dtstart']
            end = ev.get('dtend', start)
            intervals.append((start, end))
    
    return sorted(intervals)

def merge_intervals(intervals):
    """Merge overlapping time intervals.
    
    Args:
        intervals: Sorted list of (start, end) datetime tuples.
    
    Returns:
        List of merged (start, end) tuples with no overlaps.
    """
    if not intervals:
        return []
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged

def find_free_time(busy_intervals, day_start, day_end, min_duration_minutes=0):
    """Find free time slots within a day given busy intervals.
    
    Args:
        busy_intervals: List of (start, end) datetime tuples (need not be sorted/merged)
        day_start: datetime for start of available period
        day_end: datetime for end of available period
        min_duration_minutes: Minimum slot duration in minutes (0 = any slot)
    
    Returns:
        List of (start, end) datetime tuples for free slots.
    """
    merged = merge_intervals(sorted(busy_intervals))
    
    free_slots = []
    cursor = day_start
    for busy_start, busy_end in merged:
        if cursor < busy_start:
            slot = (cursor, busy_start)
            if min_duration_minutes == 0:
                free_slots.append(slot)
            else:
                duration = (busy_start - cursor).total_seconds() / 60
                if duration >= min_duration_minutes:
                    free_slots.append(slot)
        cursor = max(cursor, busy_end)
    
    if cursor < day_end:
        slot = (cursor, day_end)
        if min_duration_minutes == 0:
            free_slots.append(slot)
        else:
            duration = (day_end - cursor).total_seconds() / 60
            if duration >= min_duration_minutes:
                free_slots.append(slot)
    
    return free_slots

def find_common_free_time(calendars, day_start, day_end, min_duration_minutes=0):
    """Find free time common to all calendars.
    
    Args:
        calendars: List of Calendar objects or lists of event dicts
        day_start: datetime for start of available period
        day_end: datetime for end of available period
        min_duration_minutes: Minimum slot duration in minutes
    
    Returns:
        List of (start, end) datetime tuples for common free slots.
    """
    all_busy = []
    for cal in calendars:
        all_busy.extend(get_busy_intervals(cal))
    
    return find_free_time(all_busy, day_start, day_end, min_duration_minutes)

def has_conflict(event, existing_events):
    """Check if an event conflicts with any existing events.
    
    Args:
        event: Dict with 'dtstart' and 'dtend' keys
        existing_events: List of event dicts with 'dtstart' and 'dtend'
    
    Returns:
        True if there's a time overlap, False otherwise.
    """
    new_start = event['dtstart']
    new_end = event.get('dtend', new_start)
    
    for existing in existing_events:
        ex_start = existing['dtstart']
        ex_end = existing.get('dtend', ex_start)
        # Two intervals overlap if one starts before the other ends
        if new_start < ex_end and new_end > ex_start:
            return True
    return False
```

## Cross-Artifact Workflow Patterns

### Pattern 11: Multi-Source Reconciliation

When a task requires reading from multiple artifact types and combining data:

```python
def reconcile_email_and_calendar(email_dir, cal_path, subject_filter=None):
    """Read emails and calendar, reconcile data from both sources.
    
    Example: Extract meeting info from emails and check against calendar.
    """
    # Parse emails
    emails = parse_eml_directory(email_dir, subject_filter)
    
    # Parse calendar
    cal_events = parse_ics(cal_path)
    
    # Extract dates from email bodies
    for email_data in emails:
        email_data['extracted_dates'] = extract_dates_from_text(email_data['body'])
    
    # Cross-reference: check if email dates conflict with calendar
    for email_data in emails:
        email_data['conflicts'] = []
        for extracted_date in email_data['extracted_dates']:
            for cal_event in cal_events:
                if (cal_event['dtstart'] <= extracted_date <= cal_event.get('dtend', cal_event['dtstart'])):
                    email_data['conflicts'].append(cal_event['summary'])
    
    return emails, cal_events
```

### Pattern 12: Recipient-Based Routing

When a task requires generating per-recipient outputs:

```python
def route_by_recipient(items, output_dir, format_func):
    """Generate one output per recipient.
    
    Args:
        items: List of dicts, each with 'recipients' key (list of addresses)
               and other data fields.
        output_dir: Base directory for output files
        format_func: Function(recipient, items_for_recipient) -> (filename, content)
                     that generates the output for a single recipient.
    """
    # Group items by recipient
    recipient_items = {}
    for item in items:
        for recipient in item.get('recipients', []):
            if recipient not in recipient_items:
                recipient_items[recipient] = []
            recipient_items[recipient].append(item)
    
    # Generate per-recipient outputs
    os.makedirs(output_dir, exist_ok=True)
    outputs = {}
    for recipient, items_for_recipient in recipient_items.items():
        # Sanitize recipient name for filename
        safe_name = re.sub(r'[^\w\-.]', '_', recipient)
        filename, content = format_func(recipient, items_for_recipient)
        output_path = os.path.join(output_dir, f"{safe_name}_{filename}")
        
        if isinstance(content, bytes):
            with open(output_path, "wb") as f:
                f.write(content)
        else:
            with open(output_path, "w") as f:
                f.write(content)
        
        outputs[recipient] = output_path
    
    return outputs
```

### Pattern 13: Quantitative Analysis + Visualization

When a task requires computing statistics and generating charts:

```python
def compute_statistics(data_rows, value_column_index):
    """Compute basic statistics from spreadsheet data.
    
    Args:
        data_rows: List of row tuples (excluding header)
        value_column_index: Index of the numeric column
    
    Returns:
        Dict with count, sum, mean, min, max, median
    """
    values = [row[value_column_index] for row in data_rows 
              if row[value_column_index] is not None]
    values = [v for v in values if isinstance(v, (int, float))]
    
    if not values:
        return {"count": 0, "sum": 0, "mean": 0, "min": 0, "max": 0, "median": 0}
    
    values_sorted = sorted(values)
    n = len(values_sorted)
    median = values_sorted[n // 2] if n % 2 == 1 else (values_sorted[n // 2 - 1] + values_sorted[n // 2]) / 2
    
    return {
        "count": n,
        "sum": sum(values),
        "mean": sum(values) / n,
        "min": min(values),
        "max": max(values),
        "median": median,
    }

def generate_summary_image(filepath, stats, title="Summary"):
    """Generate a summary image with statistics."""
    lines = [
        title,
        "=" * len(title),
        f"Count: {stats['count']}",
        f"Sum: {stats['sum']}",
        f"Mean: {stats['mean']:.2f}",
        f"Min: {stats['min']}",
        f"Max: {stats['max']}",
        f"Median: {stats['median']}",
    ]
    create_text_image(filepath, lines)
```

### Pattern 14: Email Attachment Extraction

When tasks require processing files attached to emails:

```python
import email
import os
import urllib.parse

def decode_attachment_filename(part):
    """Decode an attachment filename, handling RFC 2231 encoding.
    
    Attachment filenames can be RFC 2231 encoded for non-ASCII characters:
    - Content-Disposition: attachment; filename*=utf-8''%E6%96%87%E4%BB%B6.pdf
    - part.get_filename() returns: "utf-8''%E6%96%87%E4%BB%B6.pdf"
    - This function decodes it to: "文件.pdf"
    """
    filename = part.get_filename()
    if filename is None:
        return None
    
    # Check if it looks RFC 2231 encoded (contains charset''value pattern)
    if "''" in filename:
        try:
            # Format: "charset'language'percent-encoded-value"
            parts = filename.split("''", 2)
            if len(parts) == 3:
                charset, lang, encoded = parts
                decoded = urllib.parse.unquote(encoded, encoding=charset or 'utf-8')
                return decoded
        except (ValueError, LookupError):
            # If decoding fails, return the original filename
            pass
    
    return filename

def extract_attachments(msg, output_dir=None):
    """Extract all attachments from a MIME email message.
    
    Args:
        msg: email.message.Message object
        output_dir: If provided, save attachments to this directory.
                   If None, return attachment data in memory.
    
    Returns:
        List of dicts with keys: filename, content_type, payload (bytes),
        and optionally filepath if output_dir was provided.
    """
    attachments = []
    
    if not msg.is_multipart():
        return attachments
    
    for part in msg.walk():
        # Skip the main message parts (multipart containers)
        if part.get_content_maintype() == "multipart":
            continue
        
        # Check if this part is an attachment
        filename = decode_attachment_filename(part)
        content_disposition = part.get("Content-Disposition", "")
        
        # If it has a filename or is marked as attachment, it's an attachment
        if filename or "attachment" in content_disposition.lower():
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            
            # Generate a filename if none exists
            if not filename:
                ext = ".bin"
                ct = part.get_content_type()
                if ct == "text/plain":
                    ext = ".txt"
                elif ct == "text/csv":
                    ext = ".csv"
                elif ct == "application/pdf":
                    ext = ".pdf"
                elif ct in ["application/vnd.ms-excel", 
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]:
                    ext = ".xlsx"
                filename = f"attachment{ext}"
            
            attachment = {
                "filename": filename,
                "content_type": part.get_content_type(),
                "payload": payload,
            }
            
            # Save to disk if output_dir provided
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                filepath = os.path.join(output_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(payload)
                attachment["filepath"] = filepath
            
            attachments.append(attachment)
    
    return attachments

def get_attachment_by_name(attachments, filename):
    """Find an attachment by filename (case-insensitive)."""
    for att in attachments:
        if att["filename"].lower() == filename.lower():
            return att
    return None

def get_attachments_by_type(attachments, content_type):
    """Find all attachments matching a content type (e.g., 'text/csv')."""
    return [att for att in attachments if att["content_type"] == content_type]
```

**Key details:**
- Use `msg.is_multipart()` to check if the email has multiple parts
- `decode_attachment_filename()` handles RFC 2231 encoding for non-ASCII filenames (e.g., "文件.pdf")
- `part.get_payload(decode=True)` handles Content-Transfer-Encoding automatically
- Attachments can be saved to disk or kept in memory for processing
- Use `get_attachment_by_name()` to find specific files
- Use `get_attachments_by_type()` to filter by MIME type
- Common workflow: extract XLSX attachment → process with `read_xlsx()` pattern

### Pattern 15: CSV Processing

When tasks require reading or writing CSV files:

```python
import csv

def read_csv(filepath, delimiter=',', has_header=True):
    """Read a CSV file and return data.
    
    Args:
        filepath: Path to CSV file
        delimiter: Column delimiter (default: ',')
        has_header: If True, first row is treated as header
    
    Returns:
        If has_header: dict with 'header' (list) and 'rows' (list of lists)
        If not has_header: list of lists
    """
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=delimiter)
        if has_header:
            header = next(reader)
            rows = [row for row in reader]
            return {"header": header, "rows": rows}
        else:
            return [row for row in reader]

def write_csv(filepath, data, header=None, delimiter=','):
    """Write data to a CSV file.
    
    Args:
        filepath: Path to output CSV file
        data: List of lists (rows)
        header: Optional header row (list of strings)
        delimiter: Column delimiter (default: ',')
    """
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=delimiter)
        if header:
            writer.writerow(header)
        writer.writerows(data)
```

**Key details:**
- CSV is available via stdlib `csv` module — no external dependencies needed
- Use `read_csv()` with `has_header=True` for structured data with column names
- Use `write_csv()` with optional `header` parameter
- CSV files extracted from email attachments can be processed with this pattern
- For deduplication, combine with `deduplicate_rows()` from Pattern 4

## Workflow Strategy

### Step-by-step approach for any task in this family:

1. **Parse the task instruction carefully** to identify:
   - Source artifact type(s) and location(s) — single file or multiple?
   - Filtering/selection criteria (subject, date, recipient, content)
   - Transformation logic (extract, summarize, schedule, route, analyze)
   - Whether multiple sources must be **reconciled** (combined/cross-referenced)
   - Destination artifact type(s) and location(s)
   - Whether output is **per-recipient**, **per-source**, or **consolidated**
   - Ordering/sorting requirements
   - Preservation constraints (what must remain unchanged)
   - Consistency requirements (facts shared across outputs)
   - Whether scheduling/free-time computation is needed

2. **Explore the data directory** to understand actual file structure:
   ```python
   import os
   for root, dirs, files in os.walk("data"):
       for f in files:
           print(os.path.join(root, f))
   ```

3. **Inspect source files** to understand their actual content and structure before writing processing logic. For emails, check headers and body format. For calendars, check event structure. For spreadsheets, check column layout.

4. **Determine the workflow type:**
   - **Simple filter**: Read → filter → write (v01 pattern)
   - **Cross-artifact**: Read multiple sources → reconcile → write
   - **Scheduling**: Read calendars → compute free time → write events
   - **Routing**: Read sources → group by recipient → write per-recipient outputs
   - **Analysis**: Read data → compute statistics → write summary + visualization
   - **In-place update**: Read existing artifact → merge new data → overwrite
   - **Attachment extraction**: Read emails → extract attachments → process files
   - **CSV processing**: Read/write CSV files, possibly from email attachments

5. **Implement `run()` function** that:
   - Reads source artifacts using appropriate patterns
   - Applies the specified workflow logic
   - Writes destination artifacts
   - Ensures all preservation and consistency requirements are met

6. **Test by running** the function and inspecting outputs.

### Common Output Format Patterns:

**TXT output with blocks:**
```
Subject: <subject1>
<body1>

Subject: <subject2>
<body2>
```
- Blocks separated by one blank line
- File ends with exactly one newline
- "Stripped" body = `.strip()` applied

**ICS output (new calendar):**
- Use `create_ics()` pattern
- Ensure date/time formats are correct

**ICS output (in-place update):**
- Use `update_ics_inplace()` pattern
- Preserves existing events, adds new ones

**Routing patterns:**
- One output per recipient → use `route_by_recipient()` pattern
- One output per source → maintain 1:1 mapping
- Consolidated output → merge all relevant data

## Preservation & Consistency Rules

1. **Source content must remain intact** — never modify source files unless explicitly told to update in-place
2. **Extracted facts must be exact** — dates, names, amounts must match source precisely
3. **Cross-output consistency** — if the same fact appears in multiple outputs (e.g., a date in both a TXT summary and an ICS event), it must be identical
4. **Ordering** — when sorting is specified, apply it consistently (by filename, by date, alphabetically)
5. **Completeness** — include all qualifying items, exclude all non-qualifying ones
6. **Individualized facts** — when generating per-recipient outputs, ensure each recipient's output contains only their relevant data, but any shared facts (dates, amounts) must be consistent across all outputs
7. **Quantitative consistency** — if statistics appear in both machine-readable (JSON) and visual (image) outputs, the numbers must match exactly

## Error Handling

- Always use `os.makedirs(dir, exist_ok=True)` before writing to a directory
- Handle encoding issues with fallback: `charset or "utf-8"`
- For multipart messages, walk all parts to find the correct content type
- Handle missing optional headers gracefully with `.get("Header", "")`
- **CRITICAL: Always use `normalize_to_datetime()` when reading `.dt` from icalendar** — icalendar returns either `datetime.date` (all-day events) or `datetime.datetime` (timed events), and may include timezone info. Comparing these mixed types raises `TypeError`. The `normalize_to_datetime` function (defined in Pattern 3) converts all to naive `datetime` for safe comparison.

## Checklist Before Submitting

- [ ] `solve.py` exists at `/app/solve.py`
- [ ] `run()` function is defined and callable
- [ ] All imports are at the top of the file (not inside markdown fences)
- [ ] Source files are read from the correct paths
- [ ] Filtering criteria match exactly (exact subject match, not substring)
- [ ] Output format matches specification (separators, newlines, headers)
- [ ] Output files are written to the correct paths
- [ ] Sorting order is correct
- [ ] No extra content from non-qualifying items
- [ ] File ends correctly (trailing newline as specified)
- [ ] If multiple sources: data is properly reconciled across them
- [ ] If scheduling: free-time computation accounts for all calendars
- [ ] If routing: each recipient gets only their relevant data
- [ ] If in-place update: existing content is preserved
- [ ] If cross-output: shared facts are consistent across all outputs
- [ ] If attachments: extracted with correct filenames and content types
- [ ] If CSV: header and data rows properly separated
