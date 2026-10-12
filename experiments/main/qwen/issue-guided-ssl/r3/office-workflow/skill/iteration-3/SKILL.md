---
name: office-workflow
description: >
  Reusable agent skill for office-workflow tasks: reading heterogeneous office
  artifacts (MIME email, iCalendar, PDF, XLSX), filtering by relevance
  criteria, extracting structured content, formatting destination artifacts
  (TXT, ICS, DOCX, PDF, JSON, EML), and routing outputs with consistency
  guarantees. Covers the read→filter→extract→format→route pipeline.
---

# Office-Workflow Family Skill

## 1. Family Workflow Pattern

Every task in this family follows the same five-stage pipeline:

1. **Read** — Parse source artifacts using format-appropriate libraries (MIME email via `email`, iCalendar via `icalendar`, PDF via `pymupdf`/`pdfplumber`, XLSX via `openpyxl`/`pandas`).
2. **Filter** — Select relevant items by exact-match criteria (subject, recipient, class membership, date range, etc.). Use strict equality, never substring or fuzzy matching, unless the task explicitly requests it.
3. **Extract** — Pull structured content from selected items (headers, bodies, table rows, calendar events, quantitative data).
4. **Format** — Materialize destination artifacts in the required format (TXT, ICS, JPEG, DOCX, EML, PDF, JSON).
5. **Route** — Write outputs to specified paths, preserving existing content and maintaining cross-output consistency.

## 2. MIME Email Body Extraction

This is the most error-prone mechanism in the family. An `.eml` file is a MIME message that may be multipart.

### Critical Rules

- **Never call `.strip()` on `msg.get_payload()` directly** — for multipart messages it returns a list, not a string.
- **Always use `decode=True`** when calling `get_payload()` to handle transfer encodings (base64, quoted-printable, 7bit).
- **Always walk the MIME tree** to find `text/plain` parts, since the top-level message may be `multipart/mixed`, `multipart/alternative`, etc.
- **Strip the final body text** — MIME bodies often have trailing newlines.

### Reference Implementation

```python
import email
from pathlib import Path

def extract_plain_text_body(msg):
    """Extract plain-text body from a MIME message, handling multipart correctly."""
    bodies = []
    for part in msg.walk():
        if part.get_content_type() == 'text/plain':
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            bodies.append(payload.decode(charset))
    
    if bodies:
        return bodies[0].strip()
    
    return ""

def parse_eml_file(path):
    """Parse an .eml file into an email Message object."""
    with open(path, "rb") as f:
        return email.message_from_bytes(f.read())
```

### Modern API Alternative (Python 3.6+)

If using the new `EmailMessage` API (via `policy=email.policy.default`), you can use `msg.get_body()` and `part.get_content()`:

```python
import email
from email import policy

def parse_eml_modern(path):
    with open(path, "rb") as f:
        return email.message_from_bytes(f.read(), policy=policy.default)

def extract_body_modern(msg):
    body_part = msg.get_body(preferencelist=('plain',))
    if body_part:
        return body_part.get_content().strip()
    return ""
```

**Note**: The legacy `Message` class (from `message_from_bytes` without a policy) does NOT have `get_body()`. Use the walk-based approach for maximum compatibility.

## 3. Exact-Match Filtering Principle

When tasks specify filtering criteria (subject, recipient, filename, class membership), use **exact equality** unless the task explicitly states otherwise.

### Common Pitfalls

- **Filename vs. Header mismatch**: An email file named `scholarship approved.eml` may have Subject `application approved`. Always check the actual header/content, not the filename.
- **Case sensitivity**: `Subject: Scheduled Meeting` is NOT the same as `scheduled meeting` unless the task says case-insensitive.
- **Whitespace**: Headers may have leading/trailing whitespace. Strip before comparison if the task doesn't specify exact byte matching.

### Pattern

```python
target_values = {"exact value 1", "exact value 2"}
if actual_value in target_values:
    # selected
```

## 4. Output Formatting Discipline

### Text Output (TXT)

- Each record/block: `Subject: <value>\n<body>\n`
- Adjacent blocks separated by **one blank line** (`\n\n`)
- File ends with **exactly one newline** (not zero, not two)
- Records sorted by the criterion specified (usually source filename)

### Pattern

```python
blocks = [f"Subject: {subj}\n{body}" for subj, body in selected]
output = "\n\n".join(blocks) + "\n"
Path("output.txt").write_text(output)
```

### Calendar Output (ICS)

- Preserve existing events when updating a calendar
- Use proper iCalendar format with VCALENDAR/VEVENT wrappers
- Ensure timezone consistency

### Structured Output (JSON)

- Validate JSON structure matches specification
- Ensure numeric fields are numbers, not strings
- Maintain consistent key naming

## 5. Preservation and Consistency

### Cross-Output Consistency

When a task produces multiple outputs (e.g., a PDF and an email, or a TXT and an ICS), facts that appear in both must be **identical**:
- Same dates, times, names, quantities
- Same formatting conventions
- No contradictions between outputs

### Source Preservation

- Never modify source artifacts unless explicitly instructed
- When "updating" a calendar, preserve all existing events not affected by the task
- When filtering emails, the original files remain unchanged

## 6. Routing Rules

### One-Output-Per-Source

When each source item produces one output:
- Sort outputs by source identifier (filename, ID, etc.)
- Use consistent naming conventions

### Recipient-Based Routing

When outputs are routed to specific recipients:
- Create recipient-specific directories/files
- Include only that recipient's relevant data
- Maintain individualized facts across paired outputs

## 7. Multi-Artifact Reconciliation

The spec explicitly mentions "combinations of several files whose contents must be reconciled" as a source artifact variation. When tasks involve multiple source artifacts that must be combined or cross-referenced:

### Reconciliation Patterns

**Join by Key**: When artifacts share a common identifier (email address, student ID, event ID):
```python
# Example: reconcile email list with calendar events
email_data = {extract_email_info(e) for e in emails}
calendar_data = {extract_event_info(c) for c in calendars}

# Join by recipient/email
reconciled = []
for email_info in email_data:
    matching_events = [e for e in calendar_data if e['recipient'] == email_info['recipient']]
    reconciled.append({**email_info, 'events': matching_events})
```

**Temporal Alignment**: When artifacts must be aligned by date/time:
```python
# Example: match emails to calendar events by date
for email in emails:
    email_date = parse_date(email['date'])
    matching_events = [e for e in events if same_day(e['start'], email_date)]
```

**Conflict Resolution**: When artifacts contain conflicting information:
- Prefer the most recent artifact (by modification date or content timestamp)
- Prefer the more authoritative source (e.g., official calendar over email mention)
- Flag conflicts for manual review if the task requires it

**Deduplication**: When multiple artifacts may contain duplicate entries:
```python
seen = set()
unique_items = []
for item in all_items:
    key = (item['id'], item['date'])  # or other unique identifier
    if key not in seen:
        seen.add(key)
        unique_items.append(item)
```

## 8. Artifact-Specific Extraction Patterns

### XLSX/Excel Extraction

```python
import openpyxl
from pathlib import Path

def extract_xlsx_data(path):
    """Extract structured data from Excel file."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active  # or wb[sheet_name] for specific sheet
    
    # Extract as list of dicts (header row as keys)
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    
    headers = rows[0]
    data = []
    for row in rows[1:]:
        if any(cell is not None for cell in row):  # skip empty rows
            data.append(dict(zip(headers, row)))
    
    return data

# Alternative with pandas for complex transformations
import pandas as pd
df = pd.read_excel(path, sheet_name=0)
# df.to_dict('records') for list of dicts
```

**Key considerations**:
- Use `data_only=True` to get computed values, not formulas
- Handle missing cells (None values)
- Be explicit about which sheet to read if multiple exist
- Consider data types: dates may be datetime objects, numbers may be floats

### PDF Extraction

```python
import pdfplumber
from pathlib import Path

def extract_pdf_text(path):
    """Extract text from PDF, handling multiple pages."""
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return '\n'.join(text_parts)

def extract_pdf_tables(path):
    """Extract tables from PDF."""
    tables = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_tables = page.extract_tables()
            tables.extend(page_tables)
    return tables
```

**Key considerations**:
- PDF text extraction may have layout issues (columns, headers/footers)
- Tables may need post-processing to clean up
- Some PDFs are scanned images (require OCR, not covered here)
- Preserve page breaks if task requires page-level granularity

### iCalendar Extraction

```python
from icalendar import Calendar
from pathlib import Path

def extract_calendar_events(path):
    """Extract events from iCalendar file."""
    with open(path, 'rb') as f:
        cal = Calendar.from_ical(f.read())
    
    events = []
    for component in cal.walk():
        if component.name == 'VEVENT':
            event = {
                'summary': str(component.get('summary', '')),
                'start': component.get('dtstart').dt if component.get('dtstart') else None,
                'end': component.get('dtend').dt if component.get('dtend') else None,
                'location': str(component.get('location', '')),
                'description': str(component.get('description', '')),
            }
            events.append(event)
    
    return events
```

**Key considerations**:
- Date/time objects may be date, datetime, or with timezone info
- Handle recurring events (RRULE) if present
- Preserve UID for event identification
- Some fields may be missing (optional in iCalendar spec)
- **Critical**: `component.get('dtstart').dt` returns a `date`, `datetime`, or timezone-aware `datetime` depending on the ICS file. When comparing times for overlap detection, ensure all values are the same type (convert `date` to `datetime` at midnight if needed).

### iCalendar Write Operations

The spec explicitly lists "in-place updates of existing calendars" and "conflict-free scheduling" as family operations. These require writing ICS files, not just reading them.

#### Adding Events to Existing Calendar (Write-Back)

```python
from icalendar import Calendar, Event
from datetime import datetime
from pathlib import Path

def events_overlap(start1, end1, start2, end2):
    """Check if two time ranges overlap."""
    return start1 < end2 and start2 < end1

def add_event_to_calendar(cal_path, new_event_data):
    """Add an event to an existing calendar, preserving all existing events.
    
    Args:
        cal_path: Path to existing .ics file
        new_event_data: Dict with keys: summary, start, end, location (optional), 
                       description (optional), uid (optional)
    
    Raises:
        ValueError: If new event conflicts with existing events
    """
    # 1. Read existing calendar
    with open(cal_path, 'rb') as f:
        cal = Calendar.from_ical(f.read())
    
    # 2. Check for conflicts BEFORE adding
    existing_events = [c for c in cal.walk() if c.name == 'VEVENT']
    for existing in existing_events:
        ex_start = existing.get('dtstart').dt
        ex_end = existing.get('dtend').dt
        if events_overlap(new_event_data['start'], new_event_data['end'], ex_start, ex_end):
            raise ValueError(f"Conflict with existing event: {existing.get('summary')}")
    
    # 3. Create new event
    event = Event()
    event.add('summary', new_event_data['summary'])
    event.add('dtstart', new_event_data['start'])
    event.add('dtend', new_event_data['end'])
    if 'location' in new_event_data:
        event.add('location', new_event_data['location'])
    if 'description' in new_event_data:
        event.add('description', new_event_data['description'])
    if 'uid' in new_event_data:
        event.add('uid', new_event_data['uid'])
    
    # 4. Add to calendar and write back
    cal.add_component(event)
    
    with open(cal_path, 'wb') as f:
        f.write(cal.to_ical())
```

**Critical rules**:
- Always read the existing calendar first, then add the new event, then write back
- Check for conflicts BEFORE adding to avoid corrupting the calendar
- Use `to_ical()` to serialize (not `str()` or manual formatting)
- Preserve all existing events — never overwrite the file with only the new event

#### Creating New ICS File from Scratch

```python
from icalendar import Calendar, Event
from datetime import datetime

def create_calendar(events_data, output_path):
    """Create a new ICS file with multiple events.
    
    Args:
        events_data: List of dicts with keys: summary, start, end, uid (optional)
        output_path: Path for output .ics file
    """
    cal = Calendar()
    cal.add('prodid', '-//Office Workflow//EN')
    cal.add('version', '2.0')
    
    for edata in events_data:
        event = Event()
        event.add('summary', edata['summary'])
        event.add('dtstart', edata['start'])
        event.add('dtend', edata['end'])
        if 'uid' in edata:
            event.add('uid', edata['uid'])
        cal.add_component(event)
    
    with open(output_path, 'wb') as f:
        f.write(cal.to_ical())
```

**Critical rules**:
- Always include `prodid` and `version` headers (required by iCalendar spec)
- Use `Calendar()` constructor, not `Calendar.from_ical()` (that's for reading)
- Each event should have a unique UID if provided

#### Conflict-Free Scheduling (Finding Common Free Slots)

```python
from datetime import datetime, timedelta
from icalendar import Calendar

def find_free_slots(calendars, day_start, day_end, duration=timedelta(hours=1)):
    """Find common free time slots across multiple calendars.
    
    Args:
        calendars: List of paths to .ics files
        day_start: datetime for start of search window
        day_end: datetime for end of search window
        duration: Minimum slot duration (default 1 hour)
    
    Returns:
        List of (start, end) tuples for free slots
    """
    # 1. Collect all busy intervals from all calendars
    busy = []
    for cal_path in calendars:
        with open(cal_path, 'rb') as f:
            cal = Calendar.from_ical(f.read())
        for component in cal.walk():
            if component.name == 'VEVENT':
                start = component.get('dtstart').dt
                end = component.get('dtend').dt
                if start and end:
                    busy.append((start, end))
    
    # 2. Sort by start time
    busy.sort()
    
    # 3. Merge overlapping intervals
    merged = []
    for start, end in busy:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    
    # 4. Find gaps between busy periods
    free_slots = []
    current = day_start
    for busy_start, busy_end in merged:
        if current < busy_start:
            gap_duration = busy_start - current
            if gap_duration >= duration:
                free_slots.append((current, busy_start))
        current = max(current, busy_end)
    
    # 5. Check for free time after last busy period
    if current < day_end:
        gap_duration = day_end - current
        if gap_duration >= duration:
            free_slots.append((current, day_end))
    
    return free_slots
```

**Algorithm explanation**:
1. Collect all busy intervals from all calendars
2. Sort by start time
3. Merge overlapping intervals (e.g., 10:00-11:00 and 10:30-11:30 become 10:00-11:30)
4. Walk through merged intervals, finding gaps that are at least `duration` long
5. Check for free time after the last busy period

**Critical rules**:
- Ensure all datetime objects are comparable (same timezone or all naive)
- The `duration` parameter filters out slots too short for the meeting
- Return all qualifying slots, not just the first one (let the user choose)

## 9. Destination Artifact Creation Patterns

The spec lists multiple destination artifact types. Beyond reading and filtering, tasks often require **creating** new artifacts in specific formats.

### DOCX (Word Document) Creation

```python
from docx import Document
from pathlib import Path

def create_docx(content_blocks, output_path):
    """Create a Word document with structured content.
    
    Args:
        content_blocks: List of dicts with keys: heading (optional), paragraphs (list of str)
        output_path: Path for output .docx file
    """
    doc = Document()
    
    for block in content_blocks:
        if 'heading' in block:
            doc.add_heading(block['heading'], level=1)
        
        for para_text in block.get('paragraphs', []):
            doc.add_paragraph(para_text)
    
    doc.save(output_path)

# Example: Create a report
docx_content = [
    {'heading': 'Meeting Summary', 'paragraphs': ['The meeting was productive.']},
    {'heading': 'Action Items', 'paragraphs': ['Complete report by Friday', 'Schedule follow-up']}
]
create_docx(docx_content, 'report.docx')
```

**Key considerations**:
- Use `Document()` constructor for new documents
- Use `Document(path)` to open and modify existing documents
- Headings use levels 1-9 (1 is highest)
- Tables: `doc.add_table(rows, cols)` then populate cells

### PDF Creation (ReportLab)

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pathlib import Path

def create_pdf(text_content, output_path):
    """Create a simple PDF with text content.
    
    Args:
        text_content: List of strings (one per line/paragraph)
        output_path: Path for output .pdf file
    """
    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter
    
    y_position = height - 50  # Start near top
    
    for line in text_content:
        c.drawString(50, y_position, line)
        y_position -= 20  # Move down
        
        if y_position < 50:  # New page if near bottom
            c.showPage()
            y_position = height - 50
    
    c.save()

# Example
create_pdf(['Meeting Notes', 'Date: 2024-03-25', 'Attendees: Alice, Bob'], 'notes.pdf')
```

**Key considerations**:
- ReportLab uses points (1/72 inch) for coordinates
- `letter` = (612, 792) points
- For complex layouts, use `SimpleDocTemplate` with `Paragraph` objects
- Tables: `reportlab.platypus.Table`

### EML (Email) Creation

```python
from email.message import EmailMessage
from email import policy
from pathlib import Path

def create_email(from_addr, to_addr, subject, body, output_path):
    """Create an email message file.
    
    Args:
        from_addr: Sender email address
        to_addr: Recipient email address
        subject: Email subject
        body: Plain text body
        output_path: Path for output .eml file
    """
    msg = EmailMessage()
    msg['From'] = from_addr
    msg['To'] = to_addr
    msg['Subject'] = subject
    msg.set_content(body)
    
    with open(output_path, 'wb') as f:
        f.write(msg.as_bytes(policy=policy.default))

# Example
create_email('alice@example.com', 'bob@example.com', 
             'Meeting Reminder', 'Don\'t forget the meeting at 3pm.',
             'reminder.eml')
```

**Key considerations**:
- Use `EmailMessage` (modern API) not `Message` (legacy)
- `set_content()` sets plain text body
- For HTML: `msg.add_alternative(html_content, subtype='html')`
- For attachments: `msg.add_attachment(data, maintype, subtype, filename)`
- Always use `policy=policy.default` for standards-compliant output

### Format Conversion Patterns

When tasks require converting between formats:

**TXT to DOCX**:
```python
from docx import Document

def txt_to_docx(txt_path, docx_path):
    doc = Document()
    with open(txt_path, 'r') as f:
        for line in f:
            doc.add_paragraph(line.rstrip())
    doc.save(docx_path)
```

**Email to TXT**:
```python
import email
from pathlib import Path

def email_to_txt(eml_path, txt_path):
    with open(eml_path, 'rb') as f:
        msg = email.message_from_bytes(f.read())
    
    subject = msg.get('Subject', '')
    body = extract_plain_text_body(msg)  # Use skill's extraction function
    
    output = f"Subject: {subject}\n{body}\n"
    Path(txt_path).write_text(output)
```

**Calendar to JSON**:
```python
from icalendar import Calendar
import json
from pathlib import Path

def calendar_to_json(ics_path, json_path):
    with open(ics_path, 'rb') as f:
        cal = Calendar.from_ical(f.read())
    
    events = []
    for component in cal.walk():
        if component.name == 'VEVENT':
            event = {
                'summary': str(component.get('summary', '')),
                'start': str(component.get('dtstart').dt),
                'end': str(component.get('dtend').dt),
            }
            events.append(event)
    
    with open(json_path, 'w') as f:
        json.dump(events, f, indent=2)
```

### JPEG/Visualization with PIL

The spec lists JPEG as a destination artifact and "quantitative analysis and visualization" as a workflow relation. **The task environment has PIL (Pillow) but NOT matplotlib.** All visualization must use PIL's `ImageDraw`.

#### Font Fallback Helper

The task environment may have **no TrueType fonts installed**. Always wrap `ImageFont.truetype()` in try/except and fall back to `ImageFont.load_default()`:

```python
from PIL import ImageFont

def get_font(size=12):
    """Get a font with fallback. Returns default bitmap font if no TTF available."""
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except (OSError, IOError):
        return ImageFont.load_default()
```

#### Bar Chart Creation

```python
from PIL import Image, ImageDraw, ImageFont

def create_bar_chart(data, output_path, title="", width=600, height=400):
    """Create a bar chart as JPEG using PIL.
    
    Args:
        data: List of (label, value) tuples, e.g. [("Q1", 100), ("Q2", 150)]
        output_path: Path for output .jpeg/.jpg file
        title: Chart title (optional)
        width, height: Image dimensions in pixels
    """
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)
    
    font = get_font(14)
    small_font = get_font(10)
    
    margin_left, margin_right = 60, 20
    margin_top, margin_bottom = 40, 60
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    
    if not data:
        img.save(output_path, 'JPEG', quality=95)
        return
    
    max_value = max(v for _, v in data)
    bar_width = chart_width // len(data) - 10
    
    # Draw axes
    draw.line([(margin_left, margin_top), (margin_left, height - margin_bottom)],
              fill='black', width=2)
    draw.line([(margin_left, height - margin_bottom),
               (width - margin_right, height - margin_bottom)],
              fill='black', width=2)
    
    # Draw title centered
    if title:
        bbox = draw.textbbox((0, 0), title, font=font)
        text_width = bbox[2] - bbox[0]
        draw.text(((width - text_width) // 2, 10), title, fill='black', font=font)
    
    # Draw bars
    colors = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5', '#70AD47']
    for i, (label, value) in enumerate(data):
        x = margin_left + 10 + i * (bar_width + 10)
        bar_height = int((value / max_value) * chart_height) if max_value > 0 else 0
        y = height - margin_bottom - bar_height
        
        draw.rectangle([x, y, x + bar_width, height - margin_bottom],
                       fill=colors[i % len(colors)])
        draw.text((x + bar_width // 4, y - 15), str(value),
                  fill='black', font=small_font)
        draw.text((x, height - margin_bottom + 5), label,
                  fill='black', font=small_font)
    
    img.save(output_path, 'JPEG', quality=95)
```

#### Data Table Image

```python
def create_table_image(headers, rows, output_path, title="", col_widths=None):
    """Create a data table as JPEG using PIL.
    
    Args:
        headers: List of column header strings
        rows: List of lists (each inner list is one row of data)
        output_path: Path for output .jpeg/.jpg file
        title: Table title (optional)
        col_widths: Optional list of column widths in pixels (default 120 each)
    """
    font = get_font(12)
    row_height = 25
    padding = 8
    
    if col_widths is None:
        col_widths = [120] * len(headers)
    
    table_width = sum(col_widths) + padding * 2
    table_height = (len(rows) + 1) * row_height + padding * 2 + (30 if title else 0)
    
    img = Image.new('RGB', (table_width, table_height), 'white')
    draw = ImageDraw.Draw(img)
    
    y = padding
    if title:
        draw.text((padding, y), title, fill='black', font=font)
        y += 25
    
    # Header row (blue background)
    x = padding
    for i, header in enumerate(headers):
        draw.rectangle([x, y, x + col_widths[i], y + row_height],
                       fill='#D9E2F3', outline='black')
        draw.text((x + 5, y + 5), header, fill='black', font=font)
        x += col_widths[i]
    y += row_height
    
    # Data rows (alternating colors)
    for row_idx, row in enumerate(rows):
        x = padding
        bg = '#FFFFFF' if row_idx % 2 == 0 else '#F2F2F2'
        for i, cell in enumerate(row):
            draw.rectangle([x, y, x + col_widths[i], y + row_height],
                           fill=bg, outline='black')
            draw.text((x + 5, y + 5), str(cell), fill='black', font=font)
            x += col_widths[i]
        y += row_height
    
    img.save(output_path, 'JPEG', quality=95)
```

**Key PIL rules**:
- Always use `img.save(path, 'JPEG', quality=95)` — explicit format and quality
- Use `draw.textbbox((0,0), text, font=font)` for text measurement (returns `(left, top, right, bottom)`)
- PIL uses `#RRGGBB` strings or `(R, G, B)` tuples for colors
- `Image.new('RGB', (w, h), 'white')` for white background
- **No matplotlib available** — all visualization must use PIL `ImageDraw`

## 10. Variation Dimensions

According to the family spec, tasks may vary along these axes:

- **Workflow relation**: relevance filtering, scheduling, extraction, analysis, summarization, notification, routing
- **Source artifacts**: email, calendar, PDF, XLSX, or combinations
- **Destination artifacts**: TXT, ICS, JPEG, DOCX, EML, PDF, JSON
- **Constraints**: recipient identity, subject relevance, class membership, duplicates, time windows
- **Preservation**: source integrity, cross-output fact consistency

Adapt the pipeline stages to the specific combination, but the underlying pattern remains constant. When multiple source artifacts are involved, apply the reconciliation patterns from Section 7 to combine data before formatting outputs.
