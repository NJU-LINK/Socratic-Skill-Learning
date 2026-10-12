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
