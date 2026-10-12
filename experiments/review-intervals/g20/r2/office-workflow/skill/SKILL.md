---
name: office-workflow
description: >
  General skill for office-workflow tasks that parse heterogeneous office
  artifacts (MIME email, iCalendar, PDF, XLSX), apply relevance/routing
  filters, extract or transform content, and materialize destination
  artifacts (TXT, ICS, JPEG, DOCX, EML, PDF, JSON) while preserving source
  integrity and maintaining cross-output consistency.
---

# Office Workflow Skill

## 1. Core Pipeline

Every office-workflow task follows a five-stage pipeline. The specific
artifact types, filter criteria, and output formats vary per task, but the
pipeline structure is invariant:

```
PARSE  →  FILTER  →  EXTRACT  →  FORMAT  →  WRITE
```

1. **PARSE**: Read source artifacts using the appropriate parser for each
   file type. Build an in-memory representation of each artifact's content
   and metadata.
2. **FILTER**: Select the subset of parsed artifacts (or sub-parts within
   artifacts) that match the task's routing/relevance criteria.
3. **EXTRACT**: Pull the specific data elements needed for the output —
   body text, dates, table rows, attendee lists, quantitative values, etc.
4. **FORMAT**: Structure the extracted data into the destination artifact's
   format (text blocks, calendar events, table rows, JSON objects, etc.).
5. **WRITE**: Serialize the formatted output to the destination path(s),
   respecting ordering, separator, and termination conventions.

### Implementation template

```python
from pathlib import Path

def run():
    # 1. PARSE
    sources = parse_sources(source_dir, source_types)

    # 2. FILTER
    selected = apply_filters(sources, filter_criteria)

    # 3. EXTRACT
    extracted = extract_data(selected, extraction_rules)

    # 4. FORMAT
    formatted = format_output(extracted, output_format, format_rules)

    # 5. WRITE
    write_output(formatted, output_path, output_conventions)
```

## 2. Parsing by Artifact Type

### MIME Email (.eml)

Use Python's `email` module with `policy=policy.default` for modern,
header-aware parsing.

```python
import email
from email import policy

def parse_eml(path):
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    return msg
```

**Key considerations:**
- Always use `policy.default` (not the legacy compat32) — it handles
  header decoding, content-type parsing, and charset conversion correctly.
- For multipart messages, use `msg.walk()` to iterate all parts.
- To get the complete plain-text body, **concatenate all** `text/plain`
  parts rather than stopping at the first. Reply chains and inline
  attachments can produce multiple text/plain parts.
- Use `part.get_content_type()` to check MIME types.
- Use `part.get_content()` (with policy.default) for automatic
  charset-decoded string output.
- Headers are accessed via `msg["Header-Name"]` and return decoded strings.

```python
def extract_plain_text_body(msg):
    """Extract complete plain-text body from a MIME message."""
    text_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_content()
                if isinstance(payload, str):
                    text_parts.append(payload)
    else:
        payload = msg.get_content()
        if isinstance(payload, str):
            text_parts.append(payload)
    return "\n".join(text_parts).strip()
```

#### MIME Traversal Semantics

`msg.walk()` traverses the entire MIME tree depth-first, visiting every
part at every nesting level. This has important implications:

- **`multipart/mixed`**: Contains independent parts (body + attachments).
  `walk()` visits all of them. Collecting all `text/plain` parts gives
  the body text plus any text attachments.

- **`multipart/alternative`**: Contains equivalent representations of
  the same content (e.g., text/plain + text/html). `walk()` visits both.
  For "plain-text body" extraction, collect only `text/plain` parts.
  For "complete body" extraction, you may still want only `text/plain`
  since `text/html` is an alternative representation, not additional
  content.

- **Nested structures**: A `multipart/mixed` may contain a
  `multipart/alternative` (e.g., body with both text and HTML, plus
  attachments). `walk()` descends through all levels. Filtering by
  `get_content_type() == "text/plain"` correctly collects only plain
  text regardless of nesting depth.

- **The top-level message**: `walk()` yields the top-level message
  object first. For multipart messages, its content type is
  `multipart/*`, not `text/plain`, so it's naturally skipped by the
  type filter. For non-multipart messages, the top-level object IS the
  body, which is why the `else` branch handles it directly.

**Rule of thumb**: Always filter by content type when using `walk()`.
Never assume a particular traversal order or structure.

#### Header Decoding

With `policy.default`, header values are automatically decoded from
RFC 2047 encoded words (e.g., `=?utf-8?Q?...?=`). Access headers via
`msg["Subject"]` and get decoded strings directly.

`get_content()` with `policy.default` also handles
Content-Transfer-Encoding (base64, quoted-printable) automatically,
returning decoded strings for text parts.

### iCalendar (.ics)

Use the `icalendar` library.

```python
from icalendar import Calendar

def parse_ics(path):
    with open(path, "rb") as f:
        cal = Calendar.from_ical(f.read())
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            events.append({
                "summary": str(component.get("SUMMARY", "")),
                "dtstart": component.get("DTSTART").dt if component.get("DTSTART") else None,
                "dtend": component.get("DTEND").dt if component.get("DTEND") else None,
                "location": str(component.get("LOCATION", "")),
                "description": str(component.get("DESCRIPTION", "")),
                "attendees": [str(a) for a in component.get("ATTENDEE", [])],
            })
    return events
```

### XLSX Tables

Use `openpyxl` for reading and writing spreadsheet data.

```python
from openpyxl import load_workbook

def parse_xlsx(path):
    wb = load_workbook(path, data_only=True)
    sheets = {}
    for name in wb.sheetnames:
        ws = wb[name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
        sheets[name] = rows
    return sheets
```

### PDF

No dedicated PDF-reading library may be available. Options:
- If `reportlab` is available, it handles PDF **generation** (not reading).
- For PDF text extraction, try `pip install pdfplumber` or `PyPDF2` at
  runtime if the task requires it.
- If PDF reading is not needed and only PDF writing is required, use
  `reportlab`.

```python
# PDF generation with reportlab
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def write_pdf(path, text_lines):
    c = canvas.Canvas(path, pagesize=letter)
    y = 750
    for line in text_lines:
        c.drawString(72, y, line)
        y -= 14
        if y < 72:
            c.showPage()
            y = 750
    c.save()
```

## 3. Filtering Strategies

The filter stage selects artifacts or sub-parts based on task-specific
criteria. Common patterns:

### Subject-based relevance (exact match)
```python
target_subjects = {"scheduled meeting", "application approved"}
selected = [msg for msg in messages if msg["Subject"] in target_subjects]
```

### Subject-based relevance (pattern match)
```python
import re
pattern = re.compile(r"(?i)application\s+(approved|denied)")
selected = [msg for msg in messages if pattern.search(msg["Subject"] or "")]
```

### Recipient-based routing
```python
target_recipient = "bob@example.com"
selected = [msg for msg in messages
            if target_recipient in (msg["To"] or "")]
```

### Date-range filtering (calendar events)
```python
from datetime import datetime
start = datetime(2024, 1, 1)
end = datetime(2024, 12, 31)
selected = [e for e in events
            if e["dtstart"] and start <= e["dtstart"] <= end]
```

### Content-keyword filtering
```python
keywords = {"urgent", "deadline"}
selected = [msg for msg in messages
            if any(kw in (msg.get_content() or "").lower() for kw in keywords)]
```

### Duplicate handling
When source rows may contain duplicates, deduplicate before extraction:
```python
seen = set()
unique = []
for row in rows:
    key = tuple(row[:key_columns])
    if key not in seen:
        seen.add(key)
        unique.append(row)
```

## 4. Output Format Generation

### Plain text (.txt)
```python
blocks = []
for item in selected_items:
    block = format_block(item)  # e.g., "Subject: ...\n<body>"
    # Defensive: strip trailing newlines to prevent extra blank lines
    block = block.rstrip("\n")
    blocks.append(block)

with open(output_path, "w") as f:
    f.write("\n\n".join(blocks) + "\n")
```

**Conventions:**
- Separate adjacent blocks with exactly one blank line (`\n\n`).
- End the file with exactly one trailing newline.
- No header/footer unless explicitly required.
- **Critical**: Each block must be `rstrip("\n")` before joining. If a block retains trailing newlines (common with PDF text extraction, XLSX cell content, or unmodified email bodies), the `\n\n` separator becomes `\n\n\n` or worse, violating the "exactly one blank line" requirement.

### iCalendar (.ics)
```python
from icalendar import Calendar, Event
from datetime import datetime

cal = Calendar()
cal.add("prodid", "-//Workflow//EN")
cal.add("version", "2.0")

for event_data in extracted_events:
    event = Event()
    event.add("summary", event_data["summary"])
    event.add("dtstart", event_data["dtstart"])
    event.add("dtend", event_data["dtend"])
    cal.add_component(event)

with open(output_path, "wb") as f:
    f.write(cal.to_ical())
```

### DOCX
```python
from docx import Document

doc = Document()
for section in extracted_sections:
    doc.add_heading(section["title"], level=1)
    doc.add_paragraph(section["body"])
doc.save(output_path)
```

### Structured JSON
```python
import json

output_data = {
    "items": [format_item(e) for e in extracted],
    "metadata": {"source_count": len(sources), "selected_count": len(extracted)}
}

with open(output_path, "w") as f:
    json.dump(output_data, f, indent=2, default=str)
    f.write("\n")
```

### Image (JPEG) with PIL

For bar charts and visualizations, see the concrete `write_bar_chart_jpeg`
implementation in §8 (Cross-Artifact Composition, XLSX → Chart + Summary
pattern). That implementation handles axes, labels, titles, and edge cases
(empty data, single bar).

For simple image generation:
```python
from PIL import Image, ImageDraw, ImageFont

def create_image(path, width=800, height=600):
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    # Draw content...
    img.save(path, "JPEG")
```

### Email (.eml) output
```python
from email.message import EmailMessage

def write_eml(output_path, to_addr, from_addr, subject, body):
    msg = EmailMessage()
    msg["To"] = to_addr
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with open(output_path, "wb") as f:
        f.write(msg.as_bytes())
```

## 5. Preservation and Consistency

### Source preservation
- **Never modify source files.** All operations should read sources and
  write to separate destination paths.
- When "in-place updates" are required (e.g., adding events to an existing
  calendar), read the existing file, merge new content, and write back to
  the same path — but only when the task explicitly requests this.

### Cross-output consistency
When a task produces multiple output artifacts, facts that appear in more
than one output must be identical:
- Dates extracted from an email and written to both a TXT summary and an
  ICS calendar must match exactly.
- Quantitative values in a JSON output and a chart image must use the same
  source numbers.
- Recipient names in routed emails and a routing log must agree.

**Pattern**: Extract data once into a shared data structure, then format
each output from that same structure.

```python
# Extract once
shared_data = extract_data(selected, rules)

# Format multiple outputs from the same source of truth
write_txt(shared_data, "output/summary.txt")
write_ics(shared_data, "output/events.ics")
write_json(shared_data, "output/data.json")
```

## 6. Ordering and Determinism

- **Sort outputs deterministically.** The task will specify the sort key
  (filename, date, subject, recipient, etc.). When unspecified, sort by
  source filename as a safe default.
- Use `sorted()` with an explicit key function rather than relying on
  filesystem ordering.

```python
# Sort by filename
items.sort(key=lambda x: x["source_filename"])

# Sort by date
items.sort(key=lambda x: x["date"])

# Sort by subject then filename (compound key)
items.sort(key=lambda x: (x["subject"], x["source_filename"]))
```

## 7. Routing Patterns

### One output per message
Each selected source message produces one output block/file.

### One output per recipient
Group messages by recipient, then produce one output per recipient
containing all their relevant messages.

```python
from collections import defaultdict

by_recipient = defaultdict(list)
for msg in selected:
    recipient = msg["To"]
    by_recipient[recipient].append(msg)

for recipient, messages in sorted(by_recipient.items()):
    write_output(messages, f"output/{recipient}.txt")
```

### One combined output
All selected items go into a single output file with block separators.

## 8. Cross-Artifact Composition

Many family members require parsing multiple artifact types and combining
their data. The spec explicitly mentions "combinations of several files
whose contents must be reconciled." The key principle is:

**Parse each source type independently into a common data model, then
operate on the unified model.**

### Pattern: Email + Calendar → Scheduling

**Concrete implementation for conflict-free scheduling with in-place calendar updates:**

```python
from icalendar import Calendar, Event
from datetime import datetime, timedelta
import uuid

def find_free_slots(events, search_start, search_end, duration=timedelta(hours=1)):
    """Find time windows where no existing events conflict.
    
    Algorithm: Sort events by start time, scan for gaps >= required duration.
    """
    # Collect busy intervals
    busy = []
    for e in events:
        if e["dtstart"] and e["dtend"]:
            busy.append((e["dtstart"], e["dtend"]))
    busy.sort()

    # Scan for gaps
    free_slots = []
    cursor = search_start
    for busy_start, busy_end in busy:
        if cursor < busy_start:
            gap = busy_start - cursor
            if gap >= duration:
                free_slots.append((cursor, cursor + duration))
        cursor = max(cursor, busy_end)

    # Check remaining time after last event
    if cursor < search_end and (search_end - cursor) >= duration:
        free_slots.append((cursor, cursor + duration))

    return free_slots

def merge_events_into_calendar(ics_path, new_events_data):
    """Read existing calendar, add new events, write back.
    Preserves all existing VEVENT components.
    Uses UID deduplication to prevent duplicates."""
    # Read existing calendar
    with open(ics_path, "rb") as f:
        cal = Calendar.from_ical(f.read())

    # Collect existing UIDs for deduplication
    existing_uids = set()
    for component in cal.walk():
        if component.name == "VEVENT":
            uid = component.get("UID")
            if uid:
                existing_uids.add(str(uid))

    # Add new events, skipping duplicates
    for ed in new_events_data:
        uid = ed.get("uid", str(uuid.uuid4()))
        if uid in existing_uids:
            continue
        event = Event()
        event.add("summary", ed["summary"])
        event.add("dtstart", ed["dtstart"])
        event.add("dtend", ed["dtend"])
        event.add("uid", uid)
        cal.add_component(event)

    # Write back (in-place)
    with open(ics_path, "wb") as f:
        f.write(cal.to_ical())

# Usage example:
# Parse emails for meeting requests
meeting_emails = []
for eml_path in email_dir.glob("*.eml"):
    msg = parse_eml(eml_path)
    if msg["Subject"] == "scheduled meeting":
        meeting_emails.append({
            "body": extract_plain_text_body(msg),
            "filename": eml_path.name
        })

# Parse existing calendar for conflicts
existing_events = parse_ics("calendar.ics")

# Find free time slots (e.g., next 7 days, 1-hour meetings)
search_start = datetime.now()
search_end = search_start + timedelta(days=7)
free_slots = find_free_slots(existing_events, search_start, search_end, duration=timedelta(hours=1))

# Schedule meetings in available slots
new_events = []
for i, email_data in enumerate(meeting_emails):
    if i < len(free_slots):
        slot_start, slot_end = free_slots[i]
        new_events.append({
            "summary": f"Meeting from {email_data['filename']}",
            "dtstart": slot_start,
            "dtend": slot_end,
            "uid": f"meeting-{email_data['filename']}"
        })

# Merge into calendar (preserves existing events)
merge_events_into_calendar("calendar.ics", new_events)
```

**Key principles encoded:**
1. **Read-modify-write**: Always parse the existing calendar first, don't create a new one from scratch
2. **UID deduplication**: Use UIDs to prevent duplicate events when merging
3. **Busy-interval scanning**: Sort events by start time, then scan for gaps ≥ required duration
4. **All existing VEVENTs preserved**: The `cal.add_component()` call adds new events alongside existing ones
5. **Temporal constraints**: The `find_free_slots` function respects search boundaries and duration requirements

### Pattern: XLSX → Chart + Summary

**Concrete implementation for quantitative analysis and visualization:**

```python
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

def write_bar_chart_jpeg(output_path, labels, values, title="", xlabel="", ylabel=""):
    """Generate a bar chart as JPEG using PIL.
    
    Args:
        output_path: Path to save the JPEG file
        labels: List of category labels (x-axis)
        values: List of numeric values (y-axis)
        title: Chart title (optional)
        xlabel: X-axis label (optional)
        ylabel: Y-axis label (optional)
    """
    width, height = 800, 600
    margin_left, margin_right = 80, 40
    margin_top, margin_bottom = 60, 80
    
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    # Try to use a font, fall back to default if unavailable
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except (IOError, OSError):
        font = ImageFont.load_default()
        title_font = font
    
    # Calculate chart area
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    
    # Draw axes
    draw.line([(margin_left, margin_top), (margin_left, height - margin_bottom)], fill="black", width=2)
    draw.line([(margin_left, height - margin_bottom), (width - margin_right, height - margin_bottom)], fill="black", width=2)
    
    # Calculate bar dimensions
    n_bars = len(values)
    if n_bars == 0:
        img.save(output_path, "JPEG")
        return
    
    bar_width = chart_width / n_bars * 0.7
    bar_spacing = chart_width / n_bars * 0.3
    max_value = max(values) if max(values) > 0 else 1
    
    # Draw bars
    for i, (label, value) in enumerate(zip(labels, values)):
        x = margin_left + i * (bar_width + bar_spacing) + bar_spacing / 2
        bar_height = (value / max_value) * chart_height
        y = height - margin_bottom - bar_height
        
        # Draw bar
        draw.rectangle([x, y, x + bar_width, height - margin_bottom], fill="steelblue", outline="black")
        
        # Draw label
        draw.text((x + bar_width / 2, height - margin_bottom + 5), str(label), fill="black", font=font, anchor="mt")
        
        # Draw value on top of bar
        draw.text((x + bar_width / 2, y - 5), str(value), fill="black", font=font, anchor="mb")
    
    # Draw title
    if title:
        draw.text((width / 2, 20), title, fill="black", font=title_font, anchor="mt")
    
    # Draw axis labels
    if xlabel:
        draw.text((width / 2, height - 20), xlabel, fill="black", font=font, anchor="mt")
    if ylabel:
        draw.text((20, height / 2), ylabel, fill="black", font=font, anchor="mm")
    
    img.save(output_path, "JPEG")

# Usage example:
sheets = parse_xlsx("data.xlsx")
rows = sheets["Sheet1"]
headers = rows[0]
data_rows = rows[1:]

# Extract quantitative data
column_idx = headers.index("Revenue")
labels = [row[0] for row in data_rows]  # First column as labels
values = [row[column_idx] for row in data_rows if row[column_idx]]

# Generate chart image
write_bar_chart_jpeg("chart.jpeg", labels, values, title="Revenue by Category", xlabel="Category", ylabel="Revenue ($)")

# Generate text summary
summary = f"Total: {sum(values)}\nAverage: {sum(values)/len(values):.2f}\nCount: {len(values)}"
with open("summary.txt", "w") as f:
    f.write(summary + "\n")
```

### Pattern: PDF + Email → Cross-referenced Output

**Concrete date extraction utility:**

```python
import re
from datetime import datetime

def extract_dates(text):
    """Extract dates from text, returning list of datetime objects.
    
    Handles common formats:
    - YYYY-MM-DD
    - MM/DD/YYYY
    - Month DD, YYYY (e.g., January 15, 2024)
    - DD Month YYYY (e.g., 15 January 2024)
    """
    dates = []
    
    # YYYY-MM-DD
    for match in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b', text):
        try:
            dates.append(datetime(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            pass
    
    # MM/DD/YYYY
    for match in re.finditer(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', text):
        try:
            dates.append(datetime(int(match.group(3)), int(match.group(1)), int(match.group(2))))
        except ValueError:
            pass
    
    # Month DD, YYYY (e.g., January 15, 2024)
    month_names = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'may': 5, 'june': 6, 'july': 7, 'august': 8,
        'september': 9, 'october': 10, 'november': 11, 'december': 12
    }
    for match in re.finditer(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b', text, re.IGNORECASE):
        try:
            month = month_names[match.group(1).lower()]
            dates.append(datetime(int(match.group(3)), month, int(match.group(2))))
        except (ValueError, KeyError):
            pass
    
    # DD Month YYYY (e.g., 15 January 2024)
    for match in re.finditer(r'\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b', text, re.IGNORECASE):
        try:
            month = month_names[match.group(2).lower()]
            dates.append(datetime(int(match.group(3)), month, int(match.group(1))))
        except (ValueError, KeyError):
            pass
    
    return dates

# Usage in PDF + Email cross-reference:
import subprocess
subprocess.run(["pip", "install", "pdfplumber"], capture_output=True)
import pdfplumber

pdf_dates = []
with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text() or ""
        pdf_dates.extend(extract_dates(text))

# Cross-reference with email bodies
matching_emails = []
for eml_path in email_dir.glob("*.eml"):
    msg = parse_eml(eml_path)
    body = extract_plain_text_body(msg)
    email_dates = extract_dates(body)
    # Check if any email date matches a PDF date
    if any(d in pdf_dates for d in email_dates):
        matching_emails.append((eml_path.name, msg["Subject"], body))

# Write cross-referenced output
write_output(matching_emails, "cross_reference.txt")
```

### Reconciliation Principles

When combining data from multiple sources:

1. **Normalize before comparing**: Dates from different sources may have
   different formats. Parse all dates into `datetime` objects before
   comparison.

2. **Handle missing data gracefully**: One source may reference data
   absent from another. Use `None` or sentinel values and filter
   explicitly.

3. **Preserve provenance**: Track which source each data element came
   from. This helps with debugging and with tasks that require
   source-specific formatting.

4. **Extract once, use many times**: Parse all sources into a shared
   data structure, then generate all outputs from that structure.
   This ensures cross-output consistency.

```python
# Shared data model
class WorkflowData:
    def __init__(self):
        self.emails = []      # parsed email data
        self.events = []      # parsed calendar events
        self.tables = {}      # parsed spreadsheet data
        self.extracted = {}   # cross-referenced extraction results

# Parse all sources into the model
data = WorkflowData()
data.emails = [parse_eml(p) for p in email_dir.glob("*.eml")]
data.events = parse_ics("calendar.ics")
data.tables = parse_xlsx("data.xlsx")

# Perform cross-artifact extraction
data.extracted = reconcile(data)

# Generate all outputs from the unified model
write_txt(data.extracted, "output.txt")
write_ics(data.extracted_events, "output.ics")
```

## 9. Robustness Checklist

Before finalizing any solution:

- [ ] MIME parsing uses `policy=policy.default` for correct header decoding
- [ ] All text/plain parts are concatenated (not just the first)
- [ ] Body text is stripped of leading/trailing whitespace
- [ ] **Each output block is `rstrip("\n")` before joining with the block separator** — prevents trailing newlines in content (common with PDF extraction, XLSX cells, calendar descriptions) from creating extra blank lines between blocks
- [ ] The exact number of newlines between blocks matches the spec (one blank line = `\n\n`, not `\n\n\n`)
- [ ] Output file ends with exactly one trailing newline
- [ ] Adjacent blocks separated by exactly one blank line
- [ ] Sort order matches the task specification
- [ ] Source files are not modified
- [ ] Cross-output facts are consistent (extract once, format many)
- [ ] Edge cases handled: empty body, missing headers, no matching messages
- [ ] MIME `walk()` traversal semantics understood (multipart/alternative vs multipart/mixed)
- [ ] Cross-artifact data normalized before comparison (dates → datetime, strings → common format)
- [ ] The `run()` function is callable and self-contained with all imports

## 10. Available Libraries (verified in task environment)

| Library | Purpose |
|---------|---------|
| `email` (stdlib) | MIME email parsing and generation |
| `icalendar` | iCalendar (.ics) parsing and generation |
| `openpyxl` | XLSX spreadsheet reading and writing |
| `docx` (python-docx) | DOCX document reading and writing |
| `PIL` (Pillow) | Image creation and manipulation |
| `reportlab` | PDF generation |
| `json` (stdlib) | JSON serialization |
| `csv` (stdlib) | CSV reading and writing |
| `re` (stdlib) | Regular expression matching |
| `datetime` (stdlib) | Date/time handling |
| `base64`, `quopri` (stdlib) | MIME content-transfer decoding |

## 11. Task-Solving Procedure

1. **Read the task instruction carefully.** Identify:
   - Source artifact types and locations
   - Filter/routing criteria
   - Destination artifact types and locations
   - Output format conventions (separators, termination, ordering)
   - Preservation requirements

2. **Inspect the actual source files** to understand their structure.

3. **Write `solve.py`** with a `run()` function implementing the pipeline.

4. **Test by calling `run()`** and inspecting the output.

5. **Verify edge cases**: empty inputs, missing headers, encoding issues.
