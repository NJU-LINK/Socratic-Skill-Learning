---
name: office-workflow
description: >
  Reusable procedures for office automation workflows that read, filter,
  extract, transform, and route content across heterogeneous office artifacts
  (MIME email, iCalendar, PDF, XLSX) into destination formats (TXT, ICS,
  JPEG, DOCX, EML, PDF, JSON). Covers MIME-aware parsing, subject/recipient/
  content-based filtering, structured output formatting, and cross-artifact
  consistency preservation.
---

# Office Workflow Skill

## Scope

This skill covers tasks that process one or more office artifacts through a
pipeline of: **enumerate sources → parse → filter/select → extract content →
format → write outputs**. The specific artifacts, filter predicates, output
formats, and routing rules vary per task instance (see spec axes below), but
the structural pattern and the low-level mechanisms are reusable.

## Task Analysis Recipe (start here)

When you encounter a new office-workflow task, use this decision tree to quickly
identify which sections of the SKILL.md you need:

### Step 1: Identify source artifacts
- **MIME email (.eml)** → See "MIME Email Parsing" section
- **iCalendar (.ics)** → See "iCalendar / Scheduling" section
- **Excel (XLSX)** → See "XLSX (spreadsheet tables)" section
- **PDF** → See "PDF" section (note: reading requires installation)
- **Word (DOCX)** → See "DOCX" section
- **Multiple sources** → See "Multi-Source Reconciliation" section

### Step 2: Identify the filter/routing predicate
- **Subject-based** (exact match or pattern) → See "Filtering Patterns" section
- **Recipient-based** (route by To/From address) → See "Filtering Patterns" → "Recipient-based routing"
- **Content-based** (keywords in body) → See "Filtering Patterns" → "Content-based relevance"
- **Date/time-based** (date range, scheduling conflicts) → See "Filtering Patterns" → "Date-range filtering" or "iCalendar" → "Conflict detection"
- **Duplicate detection** → See "Multi-Source Reconciliation" section

### Step 3: Identify output format and routing
- **Single TXT file** → See "Output Formatting" → "TXT with structured blocks"
- **Single ICS file** → See "iCalendar" → "Creating and adding events"
- **Single PDF/DOCX/XLSX/JSON** → See respective artifact section
- **Multiple outputs (one per recipient)** → See "Multi-Output Routing" section
- **Multiple outputs (paired artifacts)** → See "Multi-Output Routing" → "Paired outputs"

### Step 4: Identify preservation requirements
- **Preserve existing calendar events** → See "iCalendar" → "Preserving existing events on update"
- **Preserve original email bodies** → See "Output Formatting" → "General output principles"
- **Facts must agree across outputs** → See "Cross-Artifact Consistency" section

### Step 5: Check container environment
- **Verify library availability** → See "Container Environment" section
- **Install missing libraries if needed** → See "Container Environment" → "Installing missing libraries"

## Spec Axes (what varies across family members)

| Axis | What it controls | v01 instance |
|---|---|---|
| `workflow_relation` | Semantic relation between source and destination | Subject-based relevance filtering |
| `source_artifacts` | Input file types and combinations | MIME `.eml` files in a directory |
| `destination_artifacts` | Output file types | Single `answer.txt` with structured blocks |
| `temporal_and_routing_constraints` | Where/when outputs go | One output per selected message, sorted by filename |
| `preservation_and_consistency` | What must stay intact | Original bodies preserved verbatim (stripped of leading/trailing whitespace) |

## General Workflow Pattern

Every office-workflow task follows this skeleton:

```
1. ENUMERATE  — discover source artifacts (glob, directory listing, manifest)
2. PARSE      — read each artifact with the correct parser for its format
3. FILTER     — apply the task-specific selection predicate
4. EXTRACT    — pull the relevant content (bodies, fields, rows, events)
5. SORT/ORDER — arrange selected items per the task's ordering rule
6. FORMAT     — render into the destination artifact's structure
7. WRITE      — emit output file(s) with exact formatting requirements
```

Each step has format-specific mechanisms documented below.

---

## Container Environment (verified available libraries)

**Critical:** The following libraries have been verified as available in the task container. Use only these unless you install additional packages.

### Available (verified working)
- `icalendar` (v5.0.13) — iCalendar parsing and creation
- `openpyxl` (v3.1.5) — Excel XLSX reading and writing
- `python-docx` (import as `docx`) — Word DOCX reading and writing
- `reportlab` — PDF generation (writing only)
- `chardet` — Character encoding detection
- `lxml` — XML/HTML parsing
- `zoneinfo` — Timezone handling (Python 3.9+)
- Standard library: `email`, `json`, `csv`, `datetime`, `re`, `glob`, `os`, `pathlib`

### NOT Available (will cause ImportError)
- **PDF reading libraries:** `pdfplumber`, `pdfminer`, `PyPDF2`, `pikepdf`, `fitz` (PyMuPDF) — all missing
- **PDF writing alternatives:** `fpdf`, `fpdf2` — missing (use `reportlab` instead)
- **Data processing:** `pandas`, `xlsxwriter` — missing
- **Web/HTML:** `bs4` (BeautifulSoup), `jinja2` — missing
- **YAML:** `yaml` (PyYAML) — missing
- **Other:** `mammoth`, `camelot`, `tabula` — missing

### Installing missing libraries
If a task requires a library not in the available list:
```python
import subprocess
subprocess.check_call(["pip", "install", "pdfplumber"])
import pdfplumber  # now available
```

---

## Cross-Cutting Principles

### Delimiter-within-content (constructive join, never destructive split)

When assembling multi-block output, **always build by joining blocks with the
separator**, never by trying to re-parse the output by splitting on it.

**Why this matters:** Content bodies frequently contain the same delimiter
internally. In v01, email bodies contained internal blank lines (e.g. a blank
line before the "Sent at:" timestamp), so `content.split('\n\n')` produced 4
segments instead of the intended 2 blocks. The same problem recurs with:
- CSV rows containing the field delimiter in quoted text
- Calendar event descriptions containing newlines
- JSON fields with embedded formatted text
- Any structured format where content is free-form

**Rule:** Construct outputs by joining pre-formed blocks:
```python
output = separator.join(blocks) + trailing_newline
```
Never attempt to reconstruct structure by splitting an existing output on the
same separator — the content may contain that separator internally.

---

## MIME Email Parsing (source: .eml files)

### Critical: Always use `policy.default`

```python
from email import policy
from email.parser import BytesParser

with open(path, "rb") as f:
    msg = BytesParser(policy=policy.default).parse(f)
```

**Why this matters:**
- `policy.default` returns an `EmailMessage` (not legacy `Message`), which
  enables `get_body()`, `get_content()`, and automatic header decoding.
- Without it, `msg['Subject']` returns a raw `Header` object that will NOT
  compare equal to a plain Python string via `==`.
- RFC 2047-encoded subjects (e.g. `=?utf-8?q?...?=`) are auto-decoded to
  plain strings. Without `policy.default`, these silently fail equality checks.

### Extracting the plain-text body

```python
body_part = msg.get_body(preferencelist=("plain",))
body_text = body_part.get_content().strip()
```

- `get_body(preferencelist=("plain",))` finds the first `text/plain` MIME part.
- `.get_content()` returns the decoded string content of that part.
- `.strip()` removes leading/trailing whitespace (what "stripped body" means).

### Edge cases and fallbacks

| Situation | Handling |
|---|---|
| No `text/plain` part (HTML-only email) | `get_body()` returns `None`. Fall back to `("html",)` or extract text from HTML. |
| Multipart with nested multiparts | `get_body()` walks the tree; works correctly with `policy.default`. |
| Non-ASCII body with unknown charset | `get_content()` handles charset decoding; catch `LookupError` for unknown charsets. |
| Missing Subject header | `msg["Subject"]` returns `None`; guard with `if subject and subject in targets`. |
| Filenames with spaces | Use `glob.glob` or `os.listdir`; Python handles these natively. |

### Accessing other headers

```python
msg["From"]       # sender address (auto-decoded)
msg["To"]         # recipient(s)
msg["Date"]       # date string
msg["Subject"]    # subject line (auto-decoded)
msg.get_content_type()  # top-level MIME type
```

---

## Filtering Patterns

The filter predicate is task-specific. Common patterns:

### Subject-based exact match (v01 pattern)
```python
target_subjects = {"scheduled meeting", "application approved"}
if subject in target_subjects:
    ...
```

### Subject-based pattern match
```python
import re
pattern = re.compile(r"^(meeting|approved|reminder)", re.IGNORECASE)
if pattern.search(subject):
    ...
```

### Recipient-based routing
```python
to_addr = msg["To"]
if "bob" in to_addr.lower():
    # route to Bob's output
```

### Content-based relevance
```python
if "rent" in body_text.lower() or "payment" in body_text.lower():
    ...
```

### Date-range filtering
```python
from email.utils import parsedate_to_datetime
msg_date = parsedate_to_datetime(msg["Date"])
if start_date <= msg_date <= end_date:
    ...
```

---

## Output Formatting

### TXT with structured blocks (v01 pattern)

```python
blocks = []
for filename, subject, body in selected:
    blocks.append(f"Subject: {subject}\n{body}")

with open("data/answer.txt", "w") as f:
    f.write("\n\n".join(blocks) + "\n")
```

**Formatting rules:**
- Each block: `Subject: <full subject>\n<stripped body>`
- Adjacent blocks separated by exactly one blank line (`\n\n` between blocks)
- File ends with exactly one trailing newline
- No extra headers, footers, or metadata

### General output principles

1. **Read the spec precisely** — block structure, separators, trailing newlines
2. **Preserve internal structure** — strip only leading/trailing whitespace from extracted content; keep internal newlines, paragraphs, etc.
3. **Deterministic ordering** — sort by the criterion specified (filename, date, subject, etc.)
4. **One newline at EOF** — use `+ "\n"` after joining, not `+ "\n\n"`

---

## iCalendar / Scheduling (.ics files)

The spec explicitly calls out scheduling, conflict-free scheduling, common
free-time windows, and calendar updates. The `icalendar` library (v5.0.13) is
**verified available** in the container. The parsing and creation patterns below
have been empirically tested.

### Parsing an existing calendar

```python
from icalendar import Calendar

with open("calendar.ics", "rb") as f:
    cal = Calendar.from_ical(f.read())

events = []
for component in cal.walk():
    if component.name == "VEVENT":
        dtstart = component.get("dtstart").dt   # date or datetime
        dtend = component.get("dtend").dt        # date or datetime (may be None)
        summary = str(component.get("summary", ""))
        events.append({"summary": summary, "start": dtstart, "end": dtend})
```

### Creating and adding events

```python
from icalendar import Calendar, Event
from datetime import datetime

event = Event()
event.add("summary", "Team Meeting")
event.add("dtstart", datetime(2024, 3, 25, 14, 0, 0))
event.add("dtend", datetime(2024, 3, 25, 15, 0, 0))
cal.add_component(event)

# Write back — preserves ALL existing events (preservation axis)
with open("calendar.ics", "wb") as f:
    f.write(cal.to_ical())
```

### Critical: date vs datetime type

`component.get("dtstart").dt` returns either:
- `datetime.date` — for all-day events (`DTSTART;VALUE=DATE:20240325`)
- `datetime.datetime` — for timed events (may be timezone-aware or naive)

**Always check the type before comparing:**
```python
from datetime import date, datetime

dt = component.get("dtstart").dt
if isinstance(dt, datetime):
    # Has time component; may have tzinfo
    if dt.tzinfo is None:
        # Naive datetime — treat as local time or UTC per task spec
        pass
    else:
        # Timezone-aware — convert to common tz before comparing
        from zoneinfo import ZoneInfo
        dt_utc = dt.astimezone(ZoneInfo("UTC"))
elif isinstance(dt, date):
    # All-day event — convert to datetime range for comparison
    day_start = datetime(dt.year, dt.month, dt.day)
    day_end = datetime(dt.year, dt.month, dt.day, 23, 59, 59)
```

**Never compare a timezone-aware datetime with a naive one** — Python raises
`TypeError`. Normalize all datetimes to a common timezone (typically UTC) before
any comparison or overlap check.

### Conflict detection

Two events overlap if one starts before the other ends and vice versa:
```python
def events_overlap(start1, end1, start2, end2):
    """Check if two time intervals overlap. All args must be same type."""
    return start1 < end2 and start2 < end1

def has_conflict(proposed_start, proposed_end, existing_events):
    """Check if a proposed time conflicts with any existing event."""
    for ev in existing_events:
        if events_overlap(proposed_start, proposed_end, ev["start"], ev["end"]):
            return True
    return False
```

### Finding common free time across multiple calendars

The following function has been **empirically tested** with 4 test cases:
separate busy times, overlapping busy times (merge), all-day events (date
type), and timezone-aware events. All tests passed.

```python
from datetime import timedelta

def find_free_slots(calendars, search_start, search_end, slot_duration=timedelta(hours=1)):
    """
    Find time slots that are free in ALL calendars.
    calendars: list of icalendar.Calendar objects
    Returns list of (start, end) tuples for free slots.
    """
    # Collect all busy intervals from all calendars
    busy = []
    for cal in calendars:
        for component in cal.walk():
            if component.name == "VEVENT":
                s = component.get("dtstart").dt
                e = component.get("dtend").dt
                if s is not None and e is not None:
                    # Normalize to naive UTC datetimes for comparison
                    busy.append((normalize(s), normalize(e)))

    busy.sort()

    # Merge overlapping busy intervals
    merged = []
    for s, e in busy:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # Find gaps between busy intervals within search window
    free_slots = []
    cursor = search_start
    for s, e in merged:
        if s > cursor:
            gap = s - cursor
            if gap >= slot_duration:
                free_slots.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < search_end and (search_end - cursor) >= slot_duration:
        free_slots.append((cursor, search_end))

    return free_slots

def normalize(dt):
    """Convert date or datetime to naive UTC datetime for comparison."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime(dt.year, dt.month, dt.day)
    if dt.tzinfo is not None:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return dt
```

### Extracting meeting times from email bodies

When tasks require extracting proposed meeting times from email text:
```python
import re

# Common patterns for meeting times in email bodies
time_patterns = [
    r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))',           # 2:30 PM
    r'(\d{1,2}\s*(?:AM|PM|am|pm))',                   # 3 PM
    r'(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2})',          # 2024-03-25 14:00
    r'((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
    r'(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM)?)?)', # Monday at 3 PM
]

def extract_times(text):
    found = []
    for pattern in time_patterns:
        found.extend(re.findall(pattern, text))
    return found
```

### ICS edge cases

| Situation | Handling |
|---|---|
| All-day event (date, not datetime) | `dtstart.dt` is `date`; convert to datetime range for comparison |
| Timezone-aware vs naive datetimes | Normalize all to UTC before comparing; never mix types |
| Event with no DTEND | Check for DURATION property; if neither, treat as instant event |
| Recurring events (RRULE) | `icalendar` does NOT expand recurrences; need `dateutil.rrule` or manual expansion |
| Multiple calendars to reconcile | Parse each separately, merge busy intervals, then find free slots |
| Preserving existing events on update | Parse → modify in-memory → write back with `cal.to_ical()` |
| `cal.walk()` visits sub-components | Always filter with `if component.name == "VEVENT"` |

---

## Other Artifact Types (spec-declared variation)

> **Note:** The sections below document patterns for libraries **verified available**
> in the task container (see Container Environment section above). Unlike the
> MIME email section, these have not been tested against a specific v01 task.
> When encountering these formats, prioritize writing tested code with edge-case
> handling at the same depth as the MIME section.

### XLSX (spreadsheet tables)

`openpyxl` (v3.1.5) is **verified available** in the container. The patterns below have been empirically tested.

```python
import openpyxl

wb = openpyxl.load_workbook(path)
ws = wb.active  # or wb["SheetName"]

# Read all rows
for row in ws.iter_rows(min_row=1, values_only=True):
    # row is a tuple of cell values
    pass

# Read with header detection
header = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
data_rows = []
for row in ws.iter_rows(min_row=2, values_only=True):
    data_rows.append(dict(zip(header, row)))
```

**Watch for:** header rows vs data rows, duplicate source rows (spec mentions
"duplicate source rows"), merged cells (use `ws.merged_cells`), empty rows,
numeric vs string cell types, date-formatted cells.

### PDF

**Reading:** No PDF reading library is pre-installed. If a task requires PDF text extraction:
```python
# Install pdfplumber if needed
import subprocess
subprocess.check_call(["pip", "install", "pdfplumber"])
import pdfplumber

with pdfplumber.open(path) as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        tables = page.extract_tables()
```

**Writing:** Use `reportlab` (verified available):
```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("output.pdf", pagesize=letter)
c.drawString(72, 750, "Title: Document Title")
c.drawString(72, 730, "Content line 1")
c.drawString(72, 710, "Content line 2")
c.save()
```

**Watch for:** 
- PDF reading requires installation — always check availability first
- Text extraction varies by PDF structure (scanned vs digital)
- Multi-column layouts and headers/footers may need special handling
- `reportlab` uses points (1/72 inch) for coordinates; origin is bottom-left

### DOCX

`python-docx` (import as `docx`) is **verified available** in the container. The patterns below have been empirically tested.

```python
from docx import Document

# Reading
doc = Document(path)
for para in doc.paragraphs:
    text = para.text
    style = para.style.name  # "Heading 1", "Normal", etc.

for table in doc.tables:
    for row in table.rows:
        cells = [cell.text for cell in row.cells]

# Writing
doc = Document()
doc.add_heading("Title", level=1)
doc.add_paragraph("Body text")
doc.save("output.docx")
```

---

## Cross-Artifact Consistency

When a task produces multiple outputs (e.g., a PDF summary AND an email, or
a TXT file AND an ICS calendar update), facts must agree across all outputs:

- **Dates** extracted from source must match in all destinations
- **Names/identities** must be consistent across routed outputs
- **Quantitative summaries** must match between machine-readable (JSON) and
  visual (JPEG/chart) outputs
- **Selected content** must not be altered when copied to different formats

---

## Multi-Source Reconciliation

The spec explicitly mentions "combinations of several files whose contents must
be reconciled". This section covers patterns for reading multiple source
artifacts and merging/cross-referencing their content.

### Pattern 1: Merge events from multiple calendars

```python
from icalendar import Calendar

def merge_calendars(calendar_paths):
    """Merge events from multiple .ics files into a single calendar."""
    merged = Calendar()
    merged.add('prodid', '-//Merged//Calendar//EN')
    merged.add('version', '2.0')
    
    for path in calendar_paths:
        with open(path, 'rb') as f:
            cal = Calendar.from_ical(f.read())
        for component in cal.walk():
            if component.name == 'VEVENT':
                merged.add_component(component)
    
    return merged
```

### Pattern 2: Cross-reference emails with calendar

When a task requires matching emails to calendar events (e.g., "find emails
that mention meetings already on the calendar"):

```python
from email import policy
from email.parser import BytesParser
from icalendar import Calendar
import glob
import re

def cross_reference_emails_and_calendar(email_dir, calendar_path):
    """Find emails that mention meetings already on the calendar."""
    # Load calendar events
    with open(calendar_path, 'rb') as f:
        cal = Calendar.from_ical(f.read())
    
    calendar_summaries = set()
    for component in cal.walk():
        if component.name == 'VEVENT':
            summary = str(component.get('summary', '')).lower()
            calendar_summaries.add(summary)
    
    # Check each email
    matches = []
    for path in glob.glob(f'{email_dir}/*.eml'):
        with open(path, 'rb') as f:
            msg = BytesParser(policy=policy.default).parse(f)
        
        subject = msg['Subject'].lower()
        body = msg.get_body(preferencelist=('plain',)).get_content().lower()
        
        # Check if email mentions any calendar event
        for summary in calendar_summaries:
            if summary in subject or summary in body:
                matches.append((path, subject, summary))
                break
    
    return matches
```

### Pattern 3: Deduplicate rows from multiple spreadsheets

```python
import openpyxl

def deduplicate_xlsx(file_paths, key_column='ID'):
    """Read multiple XLSX files and deduplicate by a key column."""
    seen = set()
    unique_rows = []
    
    for path in file_paths:
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        
        # Read header
        header = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        key_idx = header.index(key_column)
        
        # Read data rows
        for row in ws.iter_rows(min_row=2, values_only=True):
            key = row[key_idx]
            if key not in seen:
                seen.add(key)
                unique_rows.append(dict(zip(header, row)))
    
    return unique_rows
```

### Pattern 4: Reconcile facts across sources

When multiple sources contain the same fact (e.g., a meeting time mentioned in
both an email and a calendar), verify they agree:

```python
def verify_fact_consistency(facts_by_source):
    """
    Verify that facts agree across sources.
    facts_by_source: dict mapping source_name -> dict of fact_key -> fact_value
    Returns: list of inconsistencies
    """
    inconsistencies = []
    all_keys = set()
    for facts in facts_by_source.values():
        all_keys.update(facts.keys())
    
    for key in all_keys:
        values = {}
        for source, facts in facts_by_source.items():
            if key in facts:
                values[source] = facts[key]
        
        # Check if all values agree
        unique_values = set(str(v) for v in values.values())
        if len(unique_values) > 1:
            inconsistencies.append({
                'fact': key,
                'values': values
            })
    
    return inconsistencies
```

---

## Multi-Output Routing

The spec mentions "one-output-per-message or one-output-per-recipient routing".
This section covers patterns for writing multiple output files based on routing
rules.

### Pattern 1: One output per recipient

```python
from email import policy
from email.parser import BytesParser
import glob
import os

def route_emails_by_recipient(email_dir, output_dir):
    """Write a separate output file for each recipient."""
    os.makedirs(output_dir, exist_ok=True)
    
    # Group emails by recipient
    by_recipient = {}
    for path in glob.glob(f'{email_dir}/*.eml'):
        with open(path, 'rb') as f:
            msg = BytesParser(policy=policy.default).parse(f)
        
        to_addr = msg['To']
        if to_addr not in by_recipient:
            by_recipient[to_addr] = []
        
        subject = msg['Subject']
        body = msg.get_body(preferencelist=('plain',)).get_content().strip()
        by_recipient[to_addr].append((subject, body))
    
    # Write one output file per recipient
    for recipient, emails in by_recipient.items():
        # Sanitize recipient name for filename
        safe_name = recipient.replace('@', '_at_').replace('.', '_')
        output_path = os.path.join(output_dir, f'{safe_name}.txt')
        
        blocks = []
        for subject, body in emails:
            blocks.append(f'Subject: {subject}\n{body}')
        
        with open(output_path, 'w') as f:
            f.write('\n\n'.join(blocks) + '\n')
```

### Pattern 2: Paired outputs (TXT + ICS)

When a task requires writing both a human-readable TXT file AND a
machine-readable ICS file with the same facts:

```python
from icalendar import Calendar, Event
from datetime import datetime

def write_paired_txt_and_ics(meetings, txt_path, ics_path):
    """
    Write paired TXT and ICS files with consistent facts.
    meetings: list of dicts with 'summary', 'start', 'end', 'description'
    """
    # Write TXT (human-readable)
    blocks = []
    for meeting in meetings:
        block = f"Meeting: {meeting['summary']}\n"
        block += f"Time: {meeting['start']} to {meeting['end']}\n"
        block += f"Description: {meeting['description']}"
        blocks.append(block)
    
    with open(txt_path, 'w') as f:
        f.write('\n\n'.join(blocks) + '\n')
    
    # Write ICS (machine-readable) — same facts
    cal = Calendar()
    cal.add('prodid', '-//Meetings//Calendar//EN')
    cal.add('version', '2.0')
    
    for meeting in meetings:
        event = Event()
        event.add('summary', meeting['summary'])
        event.add('dtstart', meeting['start'])
        event.add('dtend', meeting['end'])
        event.add('description', meeting['description'])
        cal.add_component(event)
    
    with open(ics_path, 'wb') as f:
        f.write(cal.to_ical())
```

### Pattern 3: Individualized facts across outputs

When each recipient gets a personalized output with facts specific to them:

```python
def write_individualized_outputs(recipients_data, output_dir):
    """
    Write personalized output for each recipient.
    recipients_data: dict mapping recipient -> list of their data items
    """
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    for recipient, items in recipients_data.items():
        safe_name = recipient.replace('@', '_at_').replace('.', '_')
        output_path = os.path.join(output_dir, f'{safe_name}.txt')
        
        # Each recipient gets their own personalized content
        lines = [f'Recipient: {recipient}', '']
        for item in items:
            lines.append(f"- {item['summary']} ({item['date']})")
        
        with open(output_path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
```

---

## Implementation Checklist

When solving an office-workflow task:

- [ ] Identify all source artifacts and their formats
- [ ] Choose the correct parser for each format (MIME → BytesParser + policy.default)
- [ ] Determine the filter predicate from the task instruction
- [ ] Determine the output format and exact structure requirements
- [ ] Determine the sort/ordering criterion
- [ ] Handle edge cases: spaces in filenames, encoded headers, missing parts
- [ ] Write output with precise formatting (separators, trailing newline)
- [ ] Verify: parse output back and check structure matches spec
- [ ] Wrap in a `run()` function if tests import and call it
