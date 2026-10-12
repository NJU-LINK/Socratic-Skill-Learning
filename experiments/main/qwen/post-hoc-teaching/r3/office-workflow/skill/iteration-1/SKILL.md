---
name: office-workflow
description: >
  General skill for office automation workflows that read, filter, transform,
  and route between office artifacts (MIME email, iCalendar, XLSX, PDF, DOCX)
  producing outputs (TXT, ICS, JPEG, DOCX, EML, PDF, JSON). Handles MIME-aware
  parsing, subject/content filtering, table extraction, scheduling, summarization,
  and recipient-based routing while preserving source content integrity and
  cross-output consistency.
---

# Office Workflow Skill

## Overview

This skill handles a family of office automation tasks where the agent must:
1. **Read** one or more source office artifacts (email, calendar, spreadsheet, PDF)
2. **Process** them according to a specified workflow relation (filtering, extraction, scheduling, summarization, routing)
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
                return text
            return decoded
        return ""
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
from datetime import datetime

def parse_ics(filepath):
    """Parse an ICS file and return events."""
    with open(filepath, "rb") as f:
        cal = Calendar.from_ical(f.read())
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            events.append({
                "summary": str(component.get("summary", "")),
                "dtstart": component.get("dtstart").dt,
                "dtend": component.get("dtend").dt if component.get("dtend") else None,
                "location": str(component.get("location", "")),
                "description": str(component.get("description", "")),
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
```

### Pattern 8: JSON Output

```python
import json

def write_json(filepath, data):
    """Write structured data as JSON."""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
```

## Workflow Strategy

### Step-by-step approach for any task in this family:

1. **Parse the task instruction carefully** to identify:
   - Source artifact type(s) and location(s)
   - Filtering/selection criteria (subject, date, recipient, content)
   - Transformation logic (extract, summarize, schedule, route)
   - Destination artifact type(s) and location(s)
   - Ordering/sorting requirements
   - Preservation constraints (what must remain unchanged)
   - Consistency requirements (facts shared across outputs)

2. **Explore the data directory** to understand actual file structure:
   ```python
   import os
   for root, dirs, files in os.walk("data"):
       for f in files:
           print(os.path.join(root, f))
   ```

3. **Inspect source files** to understand their actual content and structure before writing processing logic.

4. **Implement `run()` function** that:
   - Reads source artifacts
   - Applies the specified workflow logic
   - Writes destination artifacts
   - Ensures all preservation and consistency requirements are met

5. **Test by running** the function and inspecting outputs.

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

**ICS output:**
- Use `icalendar` library
- Preserve existing events when adding new ones
- Ensure date/time formats are correct

**Routing patterns:**
- One output per recipient → create separate files/folders
- One output per source → maintain 1:1 mapping
- Consolidated output → merge all relevant data

## Preservation & Consistency Rules

1. **Source content must remain intact** — never modify source files unless explicitly told to update in-place
2. **Extracted facts must be exact** — dates, names, amounts must match source precisely
3. **Cross-output consistency** — if the same fact appears in multiple outputs (e.g., a date in both a TXT summary and an ICS event), it must be identical
4. **Ordering** — when sorting is specified, apply it consistently (by filename, by date, alphabetically)
5. **Completeness** — include all qualifying items, exclude all non-qualifying ones

## Error Handling

- Always use `os.makedirs(dir, exist_ok=True)` before writing to a directory
- Handle encoding issues with fallback: `charset or "utf-8"`
- For multipart messages, walk all parts to find the correct content type
- Handle missing optional headers gracefully with `.get("Header", "")`

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
