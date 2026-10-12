---
name: office-workflow
description: >
  Automate office-artifact workflows that read source files (EML, ICS, PDF,
  XLSX), apply selection or transformation logic (filtering, scheduling,
  extraction, analysis, routing, format conversion), and materialise
  destination artifacts (TXT, ICS, JSON, PDF, DOCX, EML, JPEG) while
  respecting ordering, routing, and cross-output consistency constraints.
---

# Office Workflow

## 1 · Task Decomposition

Every office-workflow task follows the same pipeline. Identify each stage
from the task prompt before writing code.

| Stage | Question to answer |
|-------|--------------------|
| **Source** | Which artifact types are read, and from which paths? |
| **Selection** | What criteria pick which items (subject, date, class, relevance)? |
| **Transform** | What is computed or extracted (facts, schedules, summaries, charts)? |
| **Destination** | What artifact types are written, and to which paths? |
| **Constraints** | What ordering, routing, deduplication, or preservation rules apply? |

Write the answers as comments at the top of `solve.py` so every later step
can be verified against them.

## 2 · Source Artifact Parsers

Use the correct library for each MIME / file type. All are pre-installed.

### 2.1 EML (MIME email)

```python
import email
from email import policy
from pathlib import Path

def parse_eml(path):
    """Return (headers_dict, plain_text_body, html_body_or_None)."""
    raw = Path(path).read_bytes()
    msg = email.message_from_bytes(raw, policy=policy.default)
    headers = {k: msg.get_all(k) for k in ("Subject", "From", "To", "Date", "Cc")}
    headers = {k: v for k, v in headers.items() if v}
    plain, html = None, None
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and plain is None:
                charset = part.get_content_charset() or "us-ascii"
                plain = part.get_payload(decode=True).decode(charset, errors="replace")
            elif ct == "text/html" and html is None:
                charset = part.get_content_charset() or "us-ascii"
                html = part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = msg.get_content_charset() or "us-ascii"
        plain = msg.get_payload(decode=True).decode(charset, errors="replace")
    return headers, plain, html
```

**Key points:**
- Always use `policy.default` for modern header access.
- Use `get_payload(decode=True)` — never raw `get_payload()` for MIME parts.
- The body usually needs `.strip()` to remove leading/trailing whitespace from MIME encoding.
- Subject comparison: use exact string match on the decoded Subject header unless told otherwise.

### 2.2 ICS (iCalendar)

```python
from icalendar import Calendar

def parse_ics(path):
    """Return list of dicts with SUMMARY, DTSTART, DTEND, UID, etc."""
    cal = Calendar.from_ical(Path(path).read_bytes())
    events = []
    for comp in cal.walk():
        if comp.name == "VEVENT":
            events.append({
                "summary": str(comp.get("SUMMARY", "")),
                "dtstart": comp.get("DTSTART").dt if comp.get("DTSTART") else None,
                "dtend":   comp.get("DTEND").dt   if comp.get("DTEND")   else None,
                "uid":     str(comp.get("UID", "")),
                "raw":     comp,
            })
    return events
```

**Key points:**
- `dt` can be `date` or `datetime`; normalise with `datetime.combine(d, time.min)` if needed.
- To add events to an existing calendar, modify the `Calendar` object and write back with `cal.to_ical()`.

### 2.3 XLSX (spreadsheet)

```python
import openpyxl

def parse_xlsx(path, sheet_name=None):
    """Return (headers_list, rows_as_list_of_dicts)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[0])]
    data = []
    for row in rows[1:]:
        data.append(dict(zip(headers, row)))
    return headers, data
```

**Key points:**
- Use `data_only=True` to get cached formula values.
- Watch for `None` cells — handle with defaults.
- Duplicate row detection: compare tuples of all values or a key column.

### 2.4 PDF

```python
from pypdf import PdfReader

def parse_pdf(path):
    """Return list of page-text strings."""
    reader = PdfReader(path)
    return [page.extract_text() or "" for page in reader.pages]
```

**Key points:**
- `pypdf` extracts text; for tables inside PDFs, parse the text with regex.
- To generate PDFs, use `reportlab` (see §4.4).

## 3 · Selection & Filtering Patterns

### 3.1 Subject / header matching

```python
selected = []
for eml_path in sorted(eml_paths):
    headers, body, _ = parse_eml(eml_path)
    subject = (headers.get("Subject") or [""])[0]
    if subject in TARGET_SUBJECTS:          # exact match set
        selected.append((eml_path, headers, body))
```

- "Exactly X or Y" → set membership test on the full header string.
- "Contains keyword" → `keyword.lower() in subject.lower()`.
- Always sort by the dimension stated in the prompt (filename, date, etc.) before producing output.

### 3.2 Date / time-window filtering

```python
from datetime import datetime

def in_range(dt, start, end):
    return start <= dt <= end
```

### 3.3 Class / category membership

For XLSX data with a category column:
```python
filtered = [r for r in data if r.get("Category") in TARGET_CLASSES]
```

### 3.4 Relevance filtering

Match on multiple fields (subject + body keywords, sender domain, etc.).
Combine predicates with `and` / `or` as specified.

## 4 · Destination Artifact Writers

### 4.1 TXT

```python
def write_txt(path, blocks, separator="\n\n"):
    """Write text blocks separated by `separator`, ending with one newline."""
    content = separator.join(blocks)
    if not content.endswith("\n"):
        content += "\n"
    Path(path).write_text(content, encoding="utf-8")
```

**Critical:** The prompt will specify the exact block format and separator. Build each block as a string, join them, and ensure exactly one trailing newline.

### 4.2 ICS (calendar output)

```python
from icalendar import Calendar, Event
from datetime import datetime

def write_ics(path, events_data):
    cal = Calendar()
    cal.add("prodid", "-//Office Workflow//EN")
    cal.add("version", "2.0")
    for ev in events_data:
        e = Event()
        e.add("summary", ev["summary"])
        e.add("dtstart", ev["dtstart"])
        e.add("dtend", ev["dtend"])
        e.add("uid", ev.get("uid", f"{id(ev)}@workflow"))
        cal.add_component(e)
    Path(path).write_bytes(cal.to_ical())
```

### 4.3 JSON

```python
import json

def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, default=str) + "\n")
```

Use `default=str` to handle datetime objects.

### 4.4 PDF (via reportlab)

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

def write_pdf(path, text_lines):
    c = rl_canvas.Canvas(path, pagesize=letter)
    y = letter[1] - 50
    for line in text_lines:
        c.drawString(50, y, line)
        y -= 14
        if y < 50:
            c.showPage()
            y = letter[1] - 50
    c.save()
```

### 4.5 DOCX

```python
from docx import Document

def write_docx(path, paragraphs):
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(path)
```

### 4.6 EML (compose email)

```python
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def write_eml(path, from_addr, to_addr, subject, body_text):
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))
    Path(path).write_bytes(msg.as_bytes())
```

### 4.7 JPEG (chart or image via Pillow)

```python
from PIL import Image, ImageDraw, ImageFont

def write_jpeg(path, draw_func, size=(800, 600)):
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw_func(draw, size)
    img.save(path, "JPEG")
```

## 5 · Cross-Cutting Constraints

### 5.1 Ordering

Always determine the required sort key early:
- **By source filename**: `sorted(paths, key=lambda p: os.path.basename(p))`
- **By date**: `sorted(items, key=lambda x: x["date"])`
- **By a data column**: `sorted(rows, key=lambda r: r["ColumnName"])`

Apply sorting **after** filtering, **before** writing.

### 5.2 Routing (one-output-per-recipient / per-message)

When the task requires separate outputs per recipient or per source message:
```python
from pathlib import Path

def routed_output(base_dir, key, content, ext=".txt"):
    out_dir = Path(base_dir) / str(key)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"output{ext}").write_text(content)
```

### 5.3 Deduplication

For spreadsheet rows or calendar events, deduplicate by key:
```python
seen = set()
unique = []
for row in data:
    key = tuple(sorted(row.items()))  # or a specific column
    if key not in seen:
        seen.add(key)
        unique.append(row)
```

### 5.4 Preservation

When the task says "do not modify the original calendar" or "keep existing events":
- Read the source into memory.
- Only modify the **copy**.
- When writing, include all original items plus new ones.

### 5.5 Cross-output consistency

When multiple outputs must agree on shared facts (e.g., a summary number that
appears in both a PDF report and a JSON file):
1. Compute the shared value **once** and store it in a variable.
2. Reference that variable in every output writer.
3. Never recompute independently in separate code paths.

## 6 · Scheduling Helpers

### 6.1 Find common free-time window

```python
from datetime import datetime, timedelta

def find_free_slots(events_list, day_start, day_end, duration=timedelta(hours=1)):
    """Given a list of (start, end) busy intervals, find free slots of `duration`."""
    busy = sorted(events_list, key=lambda e: e[0])
    slots = []
    cursor = day_start
    for start, end in busy:
        if start > cursor and (start - cursor) >= duration:
            slots.append((cursor, start))
        cursor = max(cursor, end)
    if (day_end - cursor) >= duration:
        slots.append((cursor, day_end))
    return slots
```

### 6.2 Multi-person intersection

```python
def common_free_time(all_person_events, day_start, day_end, duration):
    """Intersect free slots across multiple people."""
    from functools import reduce
    per_person_free = [
        set(find_free_slots(evts, day_start, day_end, duration))
        for evts in all_person_events.values()
    ]
    common = reduce(set.intersection, per_person_free) if per_person_free else set()
    return sorted(common, key=lambda s: s[0])
```

## 7 · solve.py Template

```python
"""
Office workflow solver.

Source:      <type> at <path>
Selection:   <criteria>
Transform:   <what is computed>
Destination: <type> at <path>
Constraints: <ordering, routing, preservation>
"""

# --- all imports here ---
import email
from email import policy
from pathlib import Path
import glob
import os
# ... additional imports as needed


def run():
    # 1. Discover source files
    source_paths = sorted(glob.glob("data/emails/Bob/*.eml"))

    # 2. Parse each source artifact
    items = []
    for p in source_paths:
        # parse using §2 helpers
        ...

    # 3. Apply selection criteria
    selected = [item for item in items if <criterion>]

    # 4. Sort by required key
    selected.sort(key=lambda x: <sort_key>)

    # 5. Build output blocks / artifacts
    blocks = []
    for item in selected:
        block = f"Subject: {item['subject']}\n{item['body'].strip()}"
        blocks.append(block)

    # 6. Write destination artifact(s)
    output = "\n\n".join(blocks)
    if not output.endswith("\n"):
        output += "\n"
    Path("data/answer.txt").write_text(output, encoding="utf-8")


if __name__ == "__main__":
    run()
```

## 8 · Self-Verification Checklist

Before finalising, verify each item:

- [ ] Every source file of the required type is read (glob pattern matches all).
- [ ] Selection criteria match the prompt exactly (exact vs. contains, case-sensitive).
- [ ] Sort order matches the prompt (filename, date, column).
- [ ] Output format matches spec (block structure, separators, trailing newline).
- [ ] No content from non-selected items leaks into output.
- [ ] `run()` is callable with no arguments and performs all I/O.
- [ ] All imports are inside `solve.py`.
- [ ] If multiple outputs are required, shared facts are computed once (§5.5).
- [ ] Original source files are not modified unless the prompt requires it (§5.4).
- [ ] File paths in the code match the paths stated in the prompt.

Run a quick smoke test after writing:

```bash
cd /app && python3 -c "from solve import run; run()" && cat data/answer.txt
```

Visually inspect the output against the source data to confirm correctness.
