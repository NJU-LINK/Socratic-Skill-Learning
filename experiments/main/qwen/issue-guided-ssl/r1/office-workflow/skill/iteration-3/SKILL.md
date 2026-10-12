---
name: office-workflow
description: >
  Reusable pipeline for office automation workflows that discover source
  artifacts (email, calendar, spreadsheet, PDF), parse them with format-aware
  readers, filter by relevance criteria (subject, sender, date, recipient),
  extract structured or textual content, sort deterministically, and write
  destination artifacts (TXT, ICS, DOCX, PDF, JSON, EML, images) with exact
  output formatting. Covers MIME email parsing, iCalendar manipulation,
  XLSX table extraction, and cross-output consistency requirements.
---

# Office Workflow Automation Skill

## 1. Canonical Pipeline

Every task in this family follows the same six-stage pipeline:

```
DISCOVER → PARSE → FILTER → EXTRACT → SORT → FORMAT/WRITE
```

### Stage Details

| Stage | Purpose | Key Decisions |
|-------|---------|---------------|
| DISCOVER | Locate source artifacts | Glob by extension, walk directories, identify recipient folders |
| PARSE | Read each artifact with the right format parser | MIME email → `email` module; ICS → `icalendar`; XLSX → `openpyxl`; PDF → `reportlab` (generation only; no PDF reader verified in base environment); DOCX → `python-docx` |
| FILTER | Select relevant items by criteria | Exact string match for subjects; date ranges; recipient identity; class membership |
| EXTRACT | Pull the needed content | Body text via `walk()`; table rows; event fields; metadata |
| SORT | Deterministic ordering | By filename, date, recipient, or spec-defined key |
| FORMAT/WRITE | Produce destination artifacts | Block-join for text; ICS serialization; XLSX cell writes; JSON dumps |

## 2. MIME Email Parsing

### Reading .eml Files

```python
import email
from email import policy
from pathlib import Path

def parse_eml(filepath: Path):
    with open(filepath, 'rb') as f:
        return email.message_from_bytes(f.read(), policy=policy.default)
```

**Use `policy=policy.default`** (modern policy) for cleaner header access and proper decoding.

### Extracting Plain-Text Body

**Always use `walk()` — never assume `get_payload(0)` is the body.**

```python
def get_text_body(msg) -> str:
    text_parts = []
    for part in msg.walk():
        if part.get_content_type() == 'text/plain':
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            text_parts.append(payload.decode(charset))
    return '\n'.join(text_parts).strip()
```

Why: Emails may have `multipart/mixed` (attachments), `multipart/alternative` (HTML + plain), or nested structures. `walk()` correctly traverses all parts and selects only `text/plain`.

### Subject Filtering — Exact Match

```python
ALLOWED_SUBJECTS = {'scheduled meeting', 'application approved'}
subject = msg.get('Subject', '')
if subject not in ALLOWED_SUBJECTS:
    continue
```

**Never use substring matching** for subject-based relevance. "Reminder Rent due" contains no exact match for "scheduled meeting" but could falsely match a naive substring search for "meeting".

### Header Access

- `msg.get('Subject', '')` — returns decoded subject string
- `msg.get('From', '')` — sender
- `msg.get('To', '')` — recipient
- `msg.get('Date', '')` — date string
- For encoded headers, `policy.default` auto-decodes RFC 2047 encoded words.

## 3. Output Formatting Patterns

### Block-Separated Text Files

When writing one block per item, separated by blank lines:

```python
blocks = []
for entry in sorted_items:
    block = f"Subject: {entry['subject']}\n{entry['body']}"
    blocks.append(block)
output = '\n\n'.join(blocks) + '\n'
```

This guarantees:
- Exactly one blank line between adjacent blocks
- Exactly one trailing newline at end of file
- No off-by-one errors from manual newline counting

### "Stripped" Body

The task spec says "complete, stripped plain-text body." Apply `.strip()` to remove leading/trailing whitespace from the decoded body, but preserve internal structure (blank lines, paragraphs).

## 4. iCalendar Handling

```python
import icalendar
from datetime import datetime

# Reading
with open('calendar.ics', 'rb') as f:
    cal = icalendar.Calendar.from_ical(f.read())
for component in cal.walk():
    if component.name == 'VEVENT':
        summary = component.get('summary')
        dtstart = component.get('dtstart').dt

# Writing
cal = icalendar.Calendar()
cal.add('prodid', '-//Office Workflow//EN')
cal.add('version', '2.0')
event = icalendar.Event()
event.add('summary', 'Meeting')
event.add('dtstart', datetime(2024, 1, 15, 10, 0))
event.add('dtend', datetime(2024, 1, 15, 11, 0))
cal.add_component(event)
with open('output.ics', 'wb') as f:
    f.write(cal.to_ical())
```

## 5. XLSX Table Processing

```python
import openpyxl

# Reading
wb = openpyxl.load_workbook('data.xlsx')
ws = wb.active
for row in ws.iter_rows(min_row=2, values_only=True):  # skip header
    name, value, date = row

# Writing
wb = openpyxl.Workbook()
ws = wb.active
ws.append(['Name', 'Value', 'Date'])
ws.append(['Item 1', 42, '2024-01-01'])
wb.save('output.xlsx')
```

## 6. DOCX Generation

```python
import docx

doc = docx.Document()
doc.add_heading('Report', level=1)
doc.add_paragraph('Summary text here.')
table = doc.add_table(rows=1, cols=3)
hdr = table.rows[0].cells
hdr[0].text = 'Name'
hdr[1].text = 'Value'
hdr[2].text = 'Date'
doc.save('output.docx')
```

## 7. PDF Generation (ReportLab)

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas('output.pdf', pagesize=letter)
c.drawString(72, 720, 'Title')
c.drawString(72, 700, 'Body text here.')
c.save()
```

## 7b. EML Generation (Writing Emails)

When the task requires producing email artifacts as output:

```python
import email
from email.message import EmailMessage
from pathlib import Path

def write_eml(filepath: Path, from_addr: str, to_addr: str, 
              subject: str, body: str):
    """Write a simple plain-text email to an .eml file."""
    msg = EmailMessage()
    msg['From'] = from_addr
    msg['To'] = to_addr
    msg['Subject'] = subject
    msg.set_content(body)
    
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'wb') as f:
        f.write(msg.as_bytes())
```

For multipart emails (with attachments):

```python
from email.message import EmailMessage
import mimetypes

def write_multipart_eml(filepath: Path, from_addr: str, to_addr: str,
                        subject: str, body: str, attachments: list):
    """Write an email with attachments."""
    msg = EmailMessage()
    msg['From'] = from_addr
    msg['To'] = to_addr
    msg['Subject'] = subject
    msg.set_content(body)
    
    for attach_path in attachments:
        path = Path(attach_path)
        ctype, encoding = mimetypes.guess_type(path)
        if ctype is None:
            ctype = 'application/octet-stream'
        maintype, subtype = ctype.split('/', 1)
        
        with open(path, 'rb') as f:
            msg.add_attachment(f.read(), maintype=maintype, 
                             subtype=subtype, filename=path.name)
    
    with open(filepath, 'wb') as f:
        f.write(msg.as_bytes())
```

## 8. Cross-Cutting Principles

### Preservation and Consistency
- **Never modify source artifacts** unless the spec explicitly requires in-place updates
- When the same fact appears in multiple outputs (e.g., a date in both TXT and ICS), ensure exact agreement
- Maintain original content integrity: selected email bodies, calendar events, and table rows must be faithfully reproduced

### Routing and Recipient-Based Output
- One output per message OR one output per recipient — follow the spec precisely
- Recipient folder names must match exactly
- Subject-based relevance filtering uses exact string equality

### Deterministic Ordering
- Always sort by a stable, spec-defined key (filename, date, recipient)
- When sorting by filename, use locale-independent string comparison
- Document the sort order in comments for maintainability

### Available Libraries (verified in environment)
- `email` (stdlib) — MIME email parsing
- `icalendar` — iCalendar read/write
- `openpyxl` — XLSX read/write
- `python-docx` (`docx`) — DOCX read/write
- `reportlab` — PDF generation
- `PIL` (Pillow) — Image manipulation
- `json` (stdlib) — JSON serialization

## 9. Solution Template

```python
import email
from email import policy
from pathlib import Path

def run():
    # DISCOVER
    email_dir = Path('/app/data/emails/Bob')
    output_path = Path('/app/data/answer.txt')

    # FILTER criteria
    ALLOWED_SUBJECTS = {'scheduled meeting', 'application approved'}

    # PARSE + FILTER + EXTRACT
    selected = []
    for eml_file in sorted(email_dir.glob('*.eml')):
        with open(eml_file, 'rb') as f:
            msg = email.message_from_bytes(f.read(), policy=policy.default)

        subject = msg.get('Subject', '')
        if subject not in ALLOWED_SUBJECTS:
            continue

        # EXTRACT via walk()
        text_parts = []
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                text_parts.append(payload.decode(charset))
        body = '\n'.join(text_parts).strip()

        selected.append({
            'filename': eml_file.name,
            'subject': subject,
            'body': body,
        })

    # SORT
    selected.sort(key=lambda x: x['filename'])

    # FORMAT + WRITE
    blocks = []
    for entry in selected:
        block = f"Subject: {entry['subject']}\n{entry['body']}"
        blocks.append(block)
    output = '\n\n'.join(blocks) + '\n'

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output)
```

## 10. Common Pitfalls

1. **Using `get_payload(0)` instead of `walk()`** — breaks on multipart with attachments
2. **Substring matching for subjects** — "meeting" matches "scheduled meeting" AND "Reminder Rent due" if checking loosely
3. **Off-by-one in output formatting** — use `'\n\n'.join(blocks) + '\n'` pattern
4. **Forgetting to decode transfer-encoded payloads** — always use `get_payload(decode=True)`
5. **Hardcoding charset** — always read `get_content_charset()` with fallback to 'utf-8'
6. **Not stripping body text** — trailing newlines in MIME parts cause formatting errors

## 11. Variant Adaptation — How to Parameterize the Pipeline

The solution template in Section 9 is specific to v01. For new variants, you must **read the task spec and extract pipeline parameters**. Here's the adaptation process:

### Step 1: Identify Source Artifacts

Read the task instruction and answer:
- **What files/directories contain input data?** (e.g., `data/emails/Bob/*.eml`, `data/calendar.ics`, `data/report.xlsx`)
- **What format are they?** (MIME email, iCalendar, XLSX, PDF, DOCX, JSON)
- **Are there multiple sources that must be reconciled?** (e.g., "read emails AND calendar to find conflicts")

### Step 2: Identify Filter Criteria

- **What relevance filter applies?** (exact subject match, date range, sender identity, recipient, class membership)
- **Is it exact match or pattern match?** (spec says "exactly" → use `==`; "contains" → use `in`)
- **Are there multiple filter conditions?** (combine with `and`/`or` as spec requires)

### Step 3: Identify Extraction Requirements

- **What content must be extracted?** (body text, specific headers, table rows, event fields, dates)
- **For emails:** use `walk()` for body, `msg.get()` for headers
- **For XLSX:** use `iter_rows()` with appropriate `min_row` to skip headers
- **For iCalendar:** iterate `cal.walk()` and check `component.name`

### Step 4: Identify Sort Order

- **What is the sort key?** (filename, date, recipient, subject, or spec-defined field)
- **Ascending or descending?** (default ascending unless spec says otherwise)
- **Stable sort required?** (use Python's stable `sorted()` or `.sort()`)

### Step 5: Identify Output Format and Routing

- **What destination artifacts must be created?** (TXT, ICS, DOCX, PDF, JSON, EML, JPEG)
- **One output per item, one per recipient, or single consolidated output?**
- **What is the exact output format?** (block-separated text, CSV, JSON array, ICS calendar, etc.)
- **Are there formatting constraints?** (trailing newline, blank line separators, specific field order)

### Step 6: Identify Preservation Requirements

- **What source content must remain unchanged?** (original emails, calendar events, spreadsheet data)
- **What facts must agree across outputs?** (if same date appears in TXT and ICS, ensure exact match)
- **Are there in-place updates required?** (rare; only if spec explicitly says so)

### Adaptation Examples

**Example A: Email → ICS (Scheduling Workflow)**
- Source: `data/emails/Alice/*.eml`
- Filter: Subject exactly matches "team standup" OR "weekly sync" (exact match, not substring)
- Extract: Date/time from body text using regex, subject, sender, attendees
- Sort: By extracted date
- Output: `data/calendar.ics` with one VEVENT per email
- Preservation: Original emails unchanged; event summary matches email subject exactly

**Example B: XLSX → JSON + JPEG (Quantitative Analysis)**
- Source: `data/sales.xlsx`
- Filter: Rows where "Region" == "North" (exact match on column value)
- Extract: "Product", "Revenue", "Date" columns
- Sort: By date ascending
- Output: `data/summary.json` (structured data) AND `data/chart.jpeg` (visualization)
- Preservation: Original XLSX unchanged; facts in JSON and chart must agree

**Example C: Multi-Recipient Email Routing**
- Source: `data/emails/inbox/*.eml`
- Filter: Recipient-based (one output per recipient folder)
- Extract: Body text, subject, sender
- Sort: By filename within each recipient
- Output: `data/output/{recipient}/messages.txt` (one file per recipient)
- Preservation: Original emails unchanged; recipient folder names must match spec exactly

### Parameterization Checklist

Before writing `solve.py`, confirm you have identified:
- [ ] Source artifact paths and formats
- [ ] Filter criteria (exact vs. pattern, single vs. multiple conditions)
- [ ] Extraction fields (which headers, body parts, table columns, event properties)
- [ ] Sort key and direction
- [ ] Output artifact paths and formats
- [ ] Routing logic (one output, one per item, one per recipient)
- [ ] Formatting constraints (separators, trailing newlines, field order)
- [ ] Preservation requirements (what must not change, what must agree across outputs)

If any item is unclear, re-read the task instruction. The spec is the source of truth; do not assume v01 patterns apply without verification.

## 12. Multi-Source Reconciliation and Cross-Format Consistency

The spec's `source_artifacts` axis includes "combinations of several files whose contents must be reconciled" and the `preservation_and_consistency` axis requires "quantitative summaries shared by machine-readable and visual outputs" and "individualized facts repeated across paired PDF/email or TXT/calendar artifacts."

### General Pattern

When a task requires reading from multiple source types and producing consistent outputs:

```
1. DISCOVER all source artifacts (may be mixed formats)
2. PARSE each with its format-specific parser
3. EXTRACT relevant fields from each source
4. RECONCILE: join/merge data on a common key (date, recipient, ID, etc.)
5. VALIDATE: ensure facts agree across sources (or detect conflicts)
6. PRODUCE multiple outputs, ensuring shared facts are identical
```

### Example: Email + Calendar → Conflict Report

Task: "Read Alice's emails and calendar. Find meetings scheduled during times when she has email conflicts. Write a TXT report and update her ICS calendar."

```python
from pathlib import Path
import email
from email import policy
import icalendar
from datetime import datetime

# Step 1-2: Parse both sources
emails = []
for eml in Path('/app/data/emails/Alice').glob('*.eml'):
    with open(eml, 'rb') as f:
        msg = email.message_from_bytes(f.read(), policy=policy.default)
    # Extract date from body or headers
    emails.append({'subject': msg.get('Subject'), 'body': get_text_body(msg)})

with open('/app/data/calendar.ics', 'rb') as f:
    cal = icalendar.Calendar.from_ical(f.read())
events = []
for comp in cal.walk():
    if comp.name == 'VEVENT':
        events.append({
            'summary': str(comp.get('summary')),
            'dtstart': comp.get('dtstart').dt,
        })

# Step 3-4: Reconcile — find conflicts
conflicts = []
for event in events:
    for email_msg in emails:
        # Check if email subject mentions event time or overlaps
        if event['summary'].lower() in email_msg['subject'].lower():
            conflicts.append({
                'event': event['summary'],
                'time': event['dtstart'],
                'email_subject': email_msg['subject'],
            })

# Step 5-6: Produce consistent outputs
# TXT report
with open('/app/data/conflicts.txt', 'w') as f:
    for c in conflicts:
        f.write(f"Conflict: {c['event']} at {c['time']}\n")
        f.write(f"  Related email: {c['email_subject']}\n\n")

# ICS update — add conflict markers
for event in events:
    for c in conflicts:
        if event['summary'] == c['event']:
            event['description'] = f"CONFLICT: {c['email_subject']}"
with open('/app/data/calendar_updated.ics', 'wb') as f:
    f.write(cal.to_ical())
```

### Cross-Output Consistency Rules

When the same fact appears in multiple outputs:

1. **Exact string match**: If a date appears in both TXT and ICS, use identical formatting
2. **Numeric agreement**: If a sum appears in JSON and a chart title, ensure identical values
3. **Recipient consistency**: If an email and PDF are paired for the same recipient, names/IDs must match exactly
4. **Temporal consistency**: If events are sorted in one output, maintain the same order in related outputs

### Common Reconciliation Patterns

**Pattern A: Join on Date/Time**
- Extract dates from emails (regex on body or Date header)
- Extract dates from calendar events (DTSTART)
- Join on overlapping time windows

**Pattern B: Join on Recipient/Identity**
- Extract recipient from email To/From headers
- Extract attendee from calendar VEVENT
- Join on matching email addresses or names

**Pattern C: Join on Subject/Summary**
- Extract email Subject
- Extract calendar event SUMMARY
- Join on substring match or exact match (per spec)

**Pattern D: Aggregate + Distribute**
- Read XLSX table with per-recipient rows
- Aggregate totals (sum, count, average)
- Write JSON summary (machine-readable) AND per-recipient TXT/PDF (human-readable)
- Ensure totals in JSON match totals referenced in individual PDFs

### Validation Before Writing

Before producing outputs, validate:
- [ ] All required source files were successfully parsed
- [ ] Join keys match across sources (no orphaned records)
- [ ] Aggregated values are consistent (sum of parts equals total)
- [ ] Shared facts (dates, names, amounts) are identical across all outputs
- [ ] Output formats match spec requirements (file extensions, structure)
