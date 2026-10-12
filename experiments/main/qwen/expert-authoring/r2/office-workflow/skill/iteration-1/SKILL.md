---
name: office-workflow
description: >
  Generalized strategy for office-automation workflows that read source artifacts
  (MIME email, iCalendar, PDF, XLSX), apply a semantic relation (relevance filtering,
  conflict-free scheduling, fact extraction, quantitative analysis, summarization,
  notification, recipient-based routing, format conversion), and materialize
  destination artifacts (TXT, ICS, JPEG, DOCX, EML, PDF, JSON) while respecting
  temporal/routing constraints and preserving cross-output consistency.
---

# Office-Workflow Skill

## 1. Orientation — Read the Task Spec Completely

Before writing any code:

1. **Identify source artifacts**: Which file types are inputs? Where are they located?
2. **Identify the workflow relation**: What semantic operation connects inputs to outputs?
3. **Identify destination artifacts**: What file types must be produced? Where must they be written?
4. **Identify constraints**: Filtering predicates, sorting keys, routing rules, deduplication, scheduling windows.
5. **Identify preservation requirements**: What content must be kept intact or repeated consistently across outputs?

Create a checklist from these five items and verify it against the task instructions.

## 2. Source Artifact Parsing

### 2.1 MIME Email (`.eml`)

```python
import email
from email import policy

def parse_eml(filepath):
    with open(filepath, "rb") as f:
        msg = email.message_from_bytes(f.read(), policy=policy.default)
    headers = {k: msg[k] for k in msg.keys()}
    body_text = ""
    body_html = ""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                body_text = part.get_content()  # str
            elif ct == "text/html":
                body_html = part.get_content()
            elif part.get_filename():
                attachments.append({
                    "filename": part.get_filename(),
                    "payload": part.get_payload(decode=True),
                    "content_type": ct,
                })
    else:
        body_text = msg.get_content()
    return headers, body_text, body_html, attachments
```

**Key points:**
- Always use `policy=policy.default` (or `policy.compat32` for legacy) — never parse headers manually.
- `get_content()` returns decoded `str` for text parts, `bytes` for binary.
- For `Subject` filtering, compare `msg["Subject"]` as a plain string. Watch for encoded words — `policy.default` auto-decodes them.
- Strip bodies with `"\n".join(line.strip() for line in text.splitlines()).strip()` when the task says "stripped."

### 2.2 iCalendar (`.ics`)

```python
from icalendar import Calendar

def parse_ics(filepath):
    with open(filepath, "rb") as f:
        cal = Calendar.from_ical(f.read())
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            events.append({
                "summary": str(component.get("SUMMARY", "")),
                "dtstart": component.get("DTSTART").dt,
                "dtend": component.get("DTEND").dt,
                "location": str(component.get("LOCATION", "")),
                "uid": str(component.get("UID", "")),
                "component": component,  # keep reference for mutation
            })
    return cal, events
```

**Key points:**
- `DTSTART`/`DTEND` return `datetime.date` or `datetime.datetime` — always check `.dt` type before arithmetic.
- Preserve the original `Calendar` object if you need to write back (in-place update).
- For free-busy computation, convert all datetimes to a common timezone with `pytz`.

### 2.3 PDF

```python
from pypdf import PdfReader

def parse_pdf(filepath):
    reader = PdfReader(filepath)
    pages_text = []
    for page in reader.pages:
        pages_text.append(page.extract_text() or "")
    return pages_text
```

**Key points:**
- `extract_text()` may return `None` for scanned/image-only pages.
- For table extraction, parse the text with regex or structured heuristics (no pandas available).
- If the task requires PDF writing, use `reportlab`.

### 2.4 XLSX

```python
from openpyxl import load_workbook

def parse_xlsx(filepath):
    wb = load_workbook(filepath, data_only=True)
    sheets = {}
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
        sheets[ws.title] = rows
    return sheets
```

**Key points:**
- `data_only=True` reads cached formula values, not formula strings.
- First row is often a header — check the task spec.
- For duplicate detection, compare rows as tuples.
- Write back with `wb.save(path)` if in-place update is needed.

## 3. Workflow Relations — Decision Rules

### 3.1 Relevance Filtering

**When:** Task asks to select a subset of source artifacts matching predicates.

**Strategy:**
1. Parse each source artifact.
2. Apply predicate (subject match, keyword, date range, sender, category).
3. Collect matching artifacts with their metadata.
4. Sort by the specified key (filename, date, subject).

**Predicate patterns:**
- Exact string match: `subject == "target"` or `subject in {"a", "b"}`
- Keyword containment: `"keyword" in body.lower()`
- Date range: `start <= event_date <= end`
- Sender/domain: `from_addr.endswith("@company.com")`

### 3.2 Conflict-Free Scheduling

**When:** Task asks to find free time slots or schedule meetings without conflicts.

**Strategy:**
1. Parse all calendar sources.
2. Collect all busy intervals as `(start, end)` tuples.
3. Normalize to a common timezone.
4. Merge overlapping intervals.
5. Find gaps within the requested window.
6. If multiple participants: intersect free intervals across all calendars.

```python
def merge_intervals(intervals):
    if not intervals:
        return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged

def find_free_slots(busy_intervals, window_start, window_end, duration):
    busy = merge_intervals(busy_intervals)
    free = []
    cursor = window_start
    for bstart, bend in busy:
        if bstart > cursor:
            gap_end = min(bstart, window_end)
            if (gap_end - cursor).total_seconds() >= duration.total_seconds():
                free.append((cursor, gap_end))
        cursor = max(cursor, bend)
    if cursor < window_end:
        free.append((cursor, window_end))
    return free
```

### 3.3 Fact / Table Extraction

**When:** Task asks to pull structured data from unstructured or semi-structured sources.

**Strategy:**
1. Identify the target facts (dates, names, amounts, IDs).
2. Use regex or positional parsing on extracted text.
3. Structure into dicts or rows.
4. Validate: check for required fields, type consistency.

### 3.4 Quantitative Analysis & Visualization

**When:** Task asks for summaries, statistics, or charts.

**Strategy:**
1. Parse source data (XLSX, CSV, tables in email/PDF).
2. Compute aggregates with pure Python (no pandas): `sum()`, `len()`, `min()`, `max()`, `sorted()`.
3. For visualization without matplotlib: use `Pillow` + `ImageDraw` for bar charts, line plots, or tables rendered as images.
4. Ensure numbers in text summary match numbers in visual output exactly.

```python
from PIL import Image, ImageDraw, ImageFont

def simple_bar_chart(data, width=600, height=400, bar_color=(70, 130, 180)):
    """data: list of (label, value) tuples"""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    if not data:
        return img
    max_val = max(v for _, v in data)
    n = len(data)
    margin_left, margin_bottom = 60, 40
    chart_w = width - margin_left - 20
    chart_h = height - margin_bottom - 20
    bar_w = chart_w // n
    for i, (label, value) in enumerate(data):
        bar_h = int(chart_h * value / max_val) if max_val else 0
        x = margin_left + i * bar_w
        y = height - margin_bottom - bar_h
        draw.rectangle([x + 2, y, x + bar_w - 2, height - margin_bottom], fill=bar_color)
        draw.text((x + 4, height - margin_bottom + 4), str(label), fill="black")
    return img
```

### 3.5 Summarization + Scheduling

**When:** Task asks to summarize content AND produce calendar events.

**Strategy:**
1. Parse sources, extract facts and dates.
2. Generate summary text.
3. Generate ICS events for extracted dates.
4. Cross-check: every date mentioned in the summary must have a corresponding event, and vice versa.

### 3.6 Notification / Routing

**When:** Task asks to produce outbound messages (EML, PDF letters) for specific recipients.

**Strategy:**
1. Determine routing rule: one-output-per-message, one-output-per-recipient, or class-based.
2. For each routed output, personalize content (recipient name, specific facts).
3. Ensure each recipient folder/file name matches the routing spec.

### 3.7 Format Conversion

**When:** Task asks to convert between artifact types (e.g., email → PDF, XLSX → JSON).

**Strategy:**
1. Parse source with appropriate parser.
2. Extract relevant content.
3. Render into destination format using the appropriate generator (see §4).
4. Preserve all required content — verify field-by-field.

## 4. Destination Artifact Generation

### 4.1 TXT

```python
def write_txt(filepath, content):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
```
- Ensure file ends with exactly one newline unless spec says otherwise.
- "Stripped" text: strip each line and the overall block.

### 4.2 ICS (iCalendar)

```python
from icalendar import Calendar, Event
from datetime import datetime
import uuid

def create_ics_event(summary, dtstart, dtend, location="", uid=None):
    event = Event()
    event.add("SUMMARY", summary)
    event.add("DTSTART", dtstart)
    event.add("DTEND", dtend)
    if location:
        event.add("LOCATION", location)
    event.add("UID", uid or str(uuid.uuid4()))
    event.add("DTSTAMP", datetime.utcnow())
    return event

def write_ics(filepath, cal):
    with open(filepath, "wb") as f:
        f.write(cal.to_ical())
```

### 4.3 JPEG / Images

```python
from PIL import Image

def write_jpeg(filepath, img, quality=95):
    img.save(filepath, "JPEG", quality=quality)
```

### 4.4 DOCX

```python
from docx import Document

def write_docx(filepath, paragraphs):
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(filepath)
```

### 4.5 EML (Outbound Email)

```python
from email.message import EmailMessage

def create_eml(subject, from_addr, to_addr, body_text):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body_text)
    return msg

def write_eml(filepath, msg):
    with open(filepath, "wb") as f:
        f.write(msg.as_bytes())
```

### 4.6 PDF (with reportlab)

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def write_pdf(filepath, text_lines):
    c = canvas.Canvas(filepath, pagesize=letter)
    y = letter[1] - 40
    for line in text_lines:
        c.drawString(40, y, line)
        y -= 14
        if y < 40:
            c.showPage()
            y = letter[1] - 40
    c.save()
```

### 4.7 JSON

```python
import json

def write_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
```

## 5. Temporal & Routing Constraints

### 5.1 Sorting & Ordering
- Always confirm the sort key: filename, date, subject, recipient name.
- Python's `sorted()` is stable — use this when secondary sort is needed.
- For filename sorting: `sorted(files, key=lambda f: os.path.basename(f))`.

### 5.2 Deduplication
- Identify what constitutes a duplicate (same row, same UID, same email).
- Keep first occurrence unless spec says otherwise.
- Use tuples or frozen dicts as set keys for row-level dedup.

### 5.3 Routing Rules
- **One-output-per-message**: Each source message produces exactly one output file.
- **One-output-per-recipient**: Group messages by recipient, produce one output per recipient.
- **Class-based routing**: Route to folders/files based on category predicates.

### 5.4 Scheduling Windows
- Convert all times to a single timezone before comparison.
- Use `python-dateutil` for flexible date parsing: `from dateutil import parser as dtparser`.
- Respect business-hours constraints if specified.

## 6. Preservation & Consistency

### 6.1 Content Preservation
- When the task says "complete" body/header, include the full original text — do not truncate.
- "Stripped" means remove leading/trailing whitespace, not internal whitespace.
- For calendar in-place updates: never delete existing events unless explicitly told to.

### 6.2 Cross-Output Consistency
- If the same fact (date, amount, name) appears in multiple outputs, it must be identical.
- Build a single source-of-truth dict, then render into each output format from that dict.
- After generating all outputs, run a self-verification pass:
  1. Re-read each output file.
  2. Extract key facts.
  3. Compare against source of truth.

### 6.3 Structural Integrity
- Output files must be parseable by standard tools (valid ICS, valid JSON, valid EML).
- Always end text files with a newline unless spec says otherwise.
- Blank-line separators between blocks: exactly one blank line (`\n\n` between blocks, `\n` at end).

## 7. Solution Architecture

### 7.1 Standard `solve.py` Template

```python
import os
import glob
# ... other imports ...

def run():
    # 1. Discover source files
    # 2. Parse each source artifact
    # 3. Apply workflow relation (filter/schedule/extract/analyze/route)
    # 4. Build source-of-truth data structure
    # 5. Generate destination artifacts
    # 6. Self-verify outputs
    pass

if __name__ == "__main__":
    run()
```

### 7.2 Self-Verification Checklist

After `run()` produces outputs, verify:

- [ ] All required output files exist at the correct paths.
- [ ] File contents match the spec format (headers, separators, trailing newline).
- [ ] Filtered items match the predicate (no false positives or negatives).
- [ ] Sort order matches the spec.
- [ ] Preserved content matches source exactly.
- [ ] Cross-output facts are consistent.
- [ ] Generated files are valid (parseable ICS, JSON, EML, etc.).

### 7.3 Common Pitfalls

| Pitfall | Mitigation |
|---------|-----------|
| Using `email.parser` without `policy=default` | Always use `policy=policy.default` for proper header decoding |
| Forgetting multipart container in `.walk()` | Skip the container part; process only leaf parts |
| Timezone-naive vs aware datetime comparison | Normalize all datetimes with `pytz` before comparison |
| Off-by-one in blank-line separators | Use `"\n\n".join(blocks) + "\n"` pattern |
| Not stripping body when spec says "stripped" | Apply per-line strip + overall strip |
| Writing PDF with reportlab but forgetting `c.save()` | Always call `c.save()` or `c.showPage()` + `c.save()` |
| XLSX formula cells returning `None` | Use `data_only=True` in `load_workbook` |
| JSON not ending with newline | Add `f.write("\n")` after `json.dump()` |

## 8. Environment Notes

Available libraries (no pip install needed):
- **Email**: `email` (stdlib), `chardet`
- **Calendar**: `icalendar`, `pytz`, `python-dateutil`
- **PDF read**: `pypdf`
- **PDF write**: `reportlab`
- **XLSX**: `openpyxl`
- **DOCX**: `python-docx`
- **Images**: `Pillow`
- **XML/HTML**: `lxml`
- **Stdlib**: `json`, `csv`, `glob`, `os`, `re`, `datetime`, `uuid`, `pathlib`

**Not available**: `pandas`, `matplotlib`, `numpy`. Use pure Python or Pillow for data analysis and visualization.
