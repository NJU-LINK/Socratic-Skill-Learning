---
name: office-workflow
description: >
  Automate office-artifact workflows that read source files (EML, ICS, PDF,
  XLSX, CSV), apply selection or transformation logic (filtering, scheduling,
  extraction, analysis, routing, format conversion), and materialise
  destination artifacts (TXT, ICS, JPEG, DOCX, EML, PDF, JSON) while
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

Use the correct library for each file type. Available pre-installed libraries:
`email`, `icalendar`, `openpyxl`, `pypdf`, `python-docx`, `reportlab`,
`Pillow`, `lxml`, `chardet`, `python-dateutil`, `pytz`, `csv`.

### 2.1 EML (MIME email)

```python
import email
from email import policy
from pathlib import Path

def parse_eml(path):
    """Return (headers_dict, plain_text_body, html_body_or_None).
    headers_dict maps header name to a single decoded string (first value).
    plain_text_body is already stripped of leading/trailing whitespace.
    """
    raw = Path(path).read_bytes()
    msg = email.message_from_bytes(raw, policy=policy.default)
    headers = {}
    for key in ("Subject", "From", "To", "Date", "Cc"):
        val = msg.get(key)
        if val:
            headers[key] = str(val)

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
        ct = msg.get_content_type()
        charset = msg.get_content_charset() or "us-ascii"
        if ct == "text/plain":
            plain = msg.get_payload(decode=True).decode(charset, errors="replace")
        elif ct == "text/html":
            html = msg.get_payload(decode=True).decode(charset, errors="replace")

    # Strip body; fall back to HTML text extraction if no plain-text part
    if plain is None and html is not None:
        plain = html_to_text(html)
    body = (plain or "").strip()
    return headers, body, html
```

**Key points:**
- Use `policy.default` for modern header access; `msg.get("Subject")` returns a string directly.
- Use `get_payload(decode=True)` — never raw `get_payload()` for MIME parts.
- `.strip()` the body — MIME encoding often adds leading/trailing whitespace.
- Subject comparison: use exact string match unless the prompt says otherwise.
- If there is no plain-text part, extract text from HTML as a fallback.

### 2.2 EML attachments

```python
def extract_attachments(eml_path, output_dir):
    """Extract all non-text attachments from an EML file.
    Returns list of dicts: {filename, content_type, data (bytes)}.
    """
    raw = Path(eml_path).read_bytes()
    msg = email.message_from_bytes(raw, policy=policy.default)
    attachments = []
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        fn = part.get_filename()
        if fn:
            data = part.get_payload(decode=True)
            att_path = Path(output_dir) / fn
            att_path.write_bytes(data)
            attachments.append({
                "filename": fn,
                "content_type": part.get_content_type(),
                "path": str(att_path),
                "data": data,
            })
    return attachments
```

### 2.3 ICS (iCalendar) — with robust DTEND / DURATION / date handling

```python
from icalendar import Calendar
from datetime import datetime, date, timedelta

def _normalize_dt(val):
    """Convert icalendar date/datetime to a timezone-naive datetime."""
    if val is None:
        return None
    dt = val.dt if hasattr(val, "dt") else val
    if isinstance(dt, datetime):
        # Strip timezone info to avoid comparison errors
        return dt.replace(tzinfo=None)
    if isinstance(dt, date):
        return datetime.combine(dt, datetime.min.time())
    return dt

def parse_ics(path):
    """Return list of dicts with summary, dtstart, dtend (always datetime or None)."""
    cal = Calendar.from_ical(Path(path).read_bytes())
    events = []
    for comp in cal.walk():
        if comp.name != "VEVENT":
            continue
        dtstart = _normalize_dt(comp.get("DTSTART"))
        dtend = _normalize_dt(comp.get("DTEND"))
        # Compute DTEND from DURATION when DTEND is absent
        if dtend is None and dtstart is not None:
            dur = comp.get("DURATION")
            if dur is not None:
                delta = dur.dt if hasattr(dur, "dt") else dur
                dtend = dtstart + delta
        events.append({
            "summary": str(comp.get("SUMMARY", "")),
            "dtstart": dtstart,
            "dtend": dtend,
            "uid": str(comp.get("UID", "")),
            "raw": comp,
        })
    return events
```

**Critical edge cases handled:**
- **DURATION without DTEND**: computed as `dtstart + duration`.
- **All-day events** (`date` not `datetime`): normalised to `datetime` at midnight.
- **Timezone-aware datetimes**: stripped to naive for safe comparison.
- **Missing DTSTART/DTEND**: left as `None` rather than crashing.

### 2.4 XLSX (spreadsheet)

```python
import openpyxl

def parse_xlsx(path, sheet_name=None):
    """Return (headers_list, rows_as_list_of_dicts)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    data = []
    for row in rows[1:]:
        data.append(dict(zip(headers, row)))
    return headers, data
```

**Key points:**
- `data_only=True` returns cached formula values (not formula strings).
- Handle `None` headers and cells with explicit defaults.
- Duplicate row detection: compare `tuple(row.values())` or a key column.

### 2.5 CSV

```python
import csv

def parse_csv(path, delimiter=","):
    """Return (headers, rows_as_list_of_dicts)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        headers = reader.fieldnames or []
        rows = list(reader)
    return headers, rows
```

**Key points:**
- Use `utf-8-sig` encoding to handle BOM (byte-order mark) in Excel-exported CSVs.
- All values are strings — cast to `int`/`float` as needed before aggregation.

### 2.6 PDF

```python
from pypdf import PdfReader

def parse_pdf(path):
    """Return list of page-text strings."""
    reader = PdfReader(path)
    return [page.extract_text() or "" for page in reader.pages]
```

**Key points:**
- `pypdf` extracts text; for embedded tables, parse with regex.
- To generate PDFs, use `reportlab` (see §4.4).

## 3 · Selection & Filtering Patterns

### 3.1 Subject / header matching

```python
selected = []
for eml_path in sorted(eml_paths, key=lambda p: os.path.basename(p)):
    headers, body, _ = parse_eml(eml_path)
    subject = headers.get("Subject", "")
    if subject in TARGET_SUBJECTS:          # exact match set
        selected.append((eml_path, headers, body))
```

- "Exactly X or Y" → set membership test on the full header string.
- "Contains keyword" → `keyword.lower() in subject.lower()`.
- Always sort by the dimension stated in the prompt (filename, date, etc.) before producing output.

### 3.2 Date / time-window filtering

```python
def in_range(dt, start, end):
    """Inclusive range check. dt, start, end should all be naive datetimes."""
    return start <= dt <= end
```

### 3.3 Class / category membership

For tabular data (XLSX or CSV) with a category column:
```python
filtered = [r for r in data if r.get("Category") in TARGET_CLASSES]
```

### 3.4 Relevance filtering

Match on multiple fields (subject + body keywords, sender domain, etc.).
Combine predicates with `and` / `or` as specified.

### 3.5 Multi-source reconciliation

When combining data from multiple artifact types (e.g., email + spreadsheet):
1. Parse each source independently into a common intermediate format (list of dicts).
2. Join on a shared key (email address, name, ID).
3. Apply cross-source filters (e.g., "only rows that also appear in email subjects").

```python
def join_on_key(left_rows, right_rows, left_key, right_key):
    """Inner join two lists of dicts on specified keys."""
    right_index = {}
    for r in right_rows:
        k = r.get(right_key)
        if k is not None:
            right_index.setdefault(k, []).append(r)
    joined = []
    for l in left_rows:
        k = l.get(left_key)
        if k in right_index:
            for r in right_index[k]:
                merged = {**l, **r}
                joined.append(merged)
    return joined
```

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

**Critical:** The prompt specifies the exact block format and separator. Build each
block as a string, join them, and ensure exactly one trailing newline.

### 4.2 ICS (calendar output)

```python
from icalendar import Calendar, Event

def write_ics(path, events_data):
    """events_data: list of dicts with summary, dtstart, dtend, optional uid."""
    cal = Calendar()
    cal.add("prodid", "-//Office Workflow//EN")
    cal.add("version", "2.0")
    for ev in events_data:
        e = Event()
        e.add("summary", ev["summary"])
        e.add("dtstart", ev["dtstart"])
        if ev.get("dtend"):
            e.add("dtend", ev["dtend"])
        else:
            e.add("duration", ev.get("duration", timedelta(hours=1)))
        e.add("uid", ev.get("uid", f"{id(ev)}@workflow"))
        cal.add_component(e)
    Path(path).write_bytes(cal.to_ical())
```

**Preservation pattern:** When adding events to an existing calendar:
```python
cal = Calendar.from_ical(Path(existing_ics).read_bytes())
for new_ev in new_events:
    cal.add_component(build_event(new_ev))
Path(output_ics).write_bytes(cal.to_ical())
```

### 4.3 JSON

```python
import json

def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, default=str) + "\n")
```

Use `default=str` to serialise datetime objects.

### 4.4 PDF (via reportlab)

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

def write_pdf(path, text_lines):
    c = rl_canvas.Canvas(path, pagesize=letter)
    y = letter[1] - 50
    for line in text_lines:
        c.drawString(50, y, str(line))
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
        doc.add_paragraph(str(text))
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
from PIL import Image, ImageDraw

def write_jpeg(path, draw_func, size=(800, 600)):
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw_func(draw, size)
    img.save(path, "JPEG")
```

### 4.8 CSV output

```python
import csv

def write_csv(path, headers, rows):
    """rows: list of dicts or list of lists."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            if isinstance(row, dict):
                writer.writerow(row.get(h, "") for h in headers)
            else:
                writer.writerow(row)
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
def routed_output(base_dir, key, content, ext=".txt"):
    out_dir = Path(base_dir) / str(key)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"output{ext}").write_text(content, encoding="utf-8")
```

### 5.3 Deduplication

For tabular rows or calendar events, deduplicate by key:
```python
def deduplicate(rows, key_func):
    """key_func extracts a hashable key from each row."""
    seen = set()
    unique = []
    for row in rows:
        k = key_func(row)
        if k not in seen:
            seen.add(k)
            unique.append(row)
    return unique
```

### 5.4 Preservation

When the task says "do not modify the original calendar" or "keep existing events":
- Read the source into memory.
- Only modify a **copy** or write to a new file.
- When writing back, include all original items plus new ones (see §4.2 preservation pattern).

### 5.5 Cross-output consistency

When multiple outputs must agree on shared facts (e.g., a summary number
appearing in both a PDF report and a JSON file):
1. Compute the shared value **once** and store in a variable.
2. Reference that variable in every output writer.
3. Never recompute independently in separate code paths.

## 6 · Quantitative Analysis (without pandas)

When the task requires aggregation, statistics, or summaries from tabular data:

```python
from collections import Counter, defaultdict

def group_by(rows, key):
    """Group rows by a key function or column name."""
    groups = defaultdict(list)
    for row in rows:
        k = row.get(key) if isinstance(key, str) else key(row)
        groups[k].append(row)
    return dict(groups)

def aggregate_column(rows, col, agg="sum"):
    """Aggregate a numeric column: sum, mean, count, min, max."""
    values = [float(r[col]) for r in rows if r.get(col) is not None]
    if not values:
        return None
    if agg == "sum":   return sum(values)
    if agg == "mean":  return sum(values) / len(values)
    if agg == "count": return len(values)
    if agg == "min":   return min(values)
    if agg == "max":   return max(values)
    raise ValueError(f"Unknown aggregation: {agg}")
```

**For chart generation with Pillow**, draw simple bar/line charts:
```python
def draw_bar_chart(draw, size, data, labels):
    """data: list of numbers, labels: list of strings."""
    w, h = size
    margin = 60
    bar_area_h = h - 2 * margin
    max_val = max(data) if data else 1
    bar_w = (w - 2 * margin) // len(data) - 5
    for i, (val, label) in enumerate(zip(data, labels)):
        bar_h = int((val / max_val) * bar_area_h)
        x = margin + i * (bar_w + 5)
        y_top = h - margin - bar_h
        draw.rectangle([x, y_top, x + bar_w, h - margin], fill="steelblue")
        draw.text((x, h - margin + 5), label, fill="black")
```

## 7 · Scheduling Helpers

### 7.1 Normalise events for scheduling

Always normalise before passing to scheduling functions:
```python
def normalise_event(event):
    """Ensure dtstart/dtend are naive datetimes (not dates)."""
    start = event["dtstart"]
    end = event["dtend"]
    if start is None:
        return None
    if isinstance(start, date) and not isinstance(start, datetime):
        start = datetime.combine(start, datetime.min.time())
    if isinstance(end, date) and not isinstance(end, datetime):
        end = datetime.combine(end, datetime.min.time())
    if end is None:
        end = start + timedelta(hours=1)  # default 1-hour event
    return (start, end)
```

### 7.2 Find free-time slots

```python
def find_free_slots(busy_intervals, day_start, day_end, duration=timedelta(hours=1)):
    """Given list of (start, end) busy intervals, find free windows >= duration."""
    # Merge overlapping intervals first
    merged = []
    for start, end in sorted(busy_intervals, key=lambda e: e[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    slots = []
    cursor = day_start
    for start, end in merged:
        if start > cursor and (start - cursor) >= duration:
            slots.append((cursor, min(start, day_end)))
        cursor = max(cursor, end)
    if cursor < day_end and (day_end - cursor) >= duration:
        slots.append((cursor, day_end))
    return slots
```

**Improvements over prior version:**
- Merges overlapping intervals before scanning.
- Clips slots to `day_end` boundary.
- Handles unsorted input gracefully.

### 7.3 Multi-person free-time intersection

```python
def common_free_time(person_events, day_start, day_end, duration=timedelta(hours=1)):
    """Find time slots where ALL persons are free.
    person_events: dict mapping person -> list of (start, end) busy intervals.
    """
    all_slots = []
    for person, events in person_events.items():
        slots = find_free_slots(events, day_start, day_end, duration)
        all_slots.append(slots)
    if not all_slots:
        return []
    # Intersect: find overlaps across all persons
    result = all_slots[0]
    for other_slots in all_slots[1:]:
        result = _intersect_slots(result, other_slots)
    return [s for s in result if (s[1] - s[0]) >= duration]

def _intersect_slots(slots_a, slots_b):
    """Intersect two lists of non-overlapping sorted intervals."""
    result = []
    i = j = 0
    while i < len(slots_a) and j < len(slots_b):
        start = max(slots_a[i][0], slots_b[j][0])
        end = min(slots_a[i][1], slots_b[j][1])
        if start < end:
            result.append((start, end))
        if slots_a[i][1] < slots_b[j][1]:
            i += 1
        else:
            j += 1
    return result
```

## 8 · HTML-to-Text Fallback

When an EML has only an HTML body and no plain-text part:

```python
from html.parser import HTMLParser
import re

class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []
    def handle_data(self, data):
        self._parts.append(data)
    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self._parts.append("\n")
    def get_text(self):
        return "".join(self._parts)

def html_to_text(html_str):
    parser = _HTMLTextExtractor()
    parser.feed(html_str)
    text = parser.get_text()
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

## 9 · solve.py Templates

### 9.1 Email-filtering workflow (EML → TXT)

```python
"""
Source:      EML files at <glob_pattern>
Selection:   <criteria>
Transform:   Extract subject and body
Destination: TXT at <output_path>
Constraints: Sort by <key>; blocks separated by blank line
"""
import email
from email import policy
from pathlib import Path
import glob, os

def parse_eml(path):
    # ... use §2.1 ...
    pass

def run():
    TARGET_SUBJECTS = {"subject1", "subject2"}
    source_paths = sorted(glob.glob("<pattern>"), key=lambda p: os.path.basename(p))
    selected = []
    for p in source_paths:
        headers, body, _ = parse_eml(p)
        if headers.get("Subject", "") in TARGET_SUBJECTS:
            selected.append((p, headers, body))
    blocks = [f"Subject: {h.get('Subject', '')}\n{b}" for _, h, b in selected]
    output = "\n\n".join(blocks)
    if not output.endswith("\n"):
        output += "\n"
    Path("<output_path>").write_text(output, encoding="utf-8")

if __name__ == "__main__":
    run()
```

### 9.2 Spreadsheet-analysis workflow (XLSX/CSV → JSON + PDF)

```python
"""
Source:      XLSX at data/input.xlsx
Selection:   Filter rows by Category column
Transform:   Aggregate numeric columns per group
Destination: JSON summary + PDF report
Constraints: Shared totals across outputs (§5.5)
"""
import openpyxl, json
from pathlib import Path
from collections import defaultdict

def run():
    wb = openpyxl.load_workbook("data/input.xlsx", data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[0])]
    data = [dict(zip(headers, r)) for r in rows[1:]]
    # Filter
    filtered = [r for r in data if r.get("Category") in TARGET_CLASSES]
    # Aggregate once (§5.5)
    summary = defaultdict(lambda: {"count": 0, "total": 0.0})
    for r in filtered:
        cat = r["Category"]
        summary[cat]["count"] += 1
        summary[cat]["total"] += float(r.get("Amount", 0))
    summary = dict(summary)
    # Write JSON
    Path("data/summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n")
    # Write PDF using same summary
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import letter
    c = rl_canvas.Canvas("data/report.pdf", pagesize=letter)
    y = letter[1] - 50
    for cat, vals in summary.items():
        c.drawString(50, y, f"{cat}: count={vals['count']}, total={vals['total']:.2f}")
        y -= 20
    c.save()

if __name__ == "__main__":
    run()
```

### 9.3 Scheduling workflow (ICS → ICS)

```python
"""
Source:      ICS files for multiple people
Selection:   Events within target date range
Transform:   Find common free slot
Destination: New ICS with meeting event
Constraints: Do not modify source calendars (§5.4)
"""
from icalendar import Calendar
from datetime import datetime, timedelta
from pathlib import Path

def run():
    # Parse all calendars, normalise events (§7.1)
    person_events = {}
    for ics_path in Path("data/calendars").glob("*.ics"):
        cal = Calendar.from_ical(ics_path.read_bytes())
        events = []
        for comp in cal.walk():
            if comp.name == "VEVENT":
                # Use robust parsing from §2.3
                ...
        person_events[ics_path.stem] = events
    # Find common free time (§7.3)
    day_start = datetime(2024, 3, 15, 9, 0)
    day_end   = datetime(2024, 3, 15, 17, 0)
    slots = common_free_time(person_events, day_start, day_end)
    # Write new event
    ...

if __name__ == "__main__":
    run()
```

### 9.4 Multi-source workflow (EML + XLSX → routed outputs)

```python
"""
Source:      EML emails + XLSX roster
Selection:   Emails matching criteria + roster rows
Transform:   Cross-reference sender with roster
Destination: Per-recipient routed outputs
Constraints: One output per recipient (§5.2)
"""
def run():
    # 1. Parse roster
    headers, roster = parse_xlsx("data/roster.xlsx")
    # 2. Parse emails and extract sender info
    for eml_path in sorted(glob.glob("data/emails/*/*.eml")):
        eml_headers, body, _ = parse_eml(eml_path)
        sender = eml_headers.get("From", "")
        # 3. Match sender to roster
        matched = [r for r in roster if r.get("Email") in sender]
        for person in matched:
            # 4. Route output
            routed_output("data/outputs", person["Name"],
                          f"Report for {person['Name']}\n{body}")
```

## 10 · Self-Verification Checklist

Before finalising, verify each item:

- [ ] Every source file of the required type is read (glob pattern covers all files, including names with spaces).
- [ ] Selection criteria match the prompt exactly (exact vs. contains, case-sensitive).
- [ ] Sort order matches the prompt (filename, date, column).
- [ ] Output format matches spec (block structure, separators, trailing newline).
- [ ] No content from non-selected items leaks into output.
- [ ] `run()` is callable with no arguments and performs all I/O.
- [ ] All imports are inside `solve.py`.
- [ ] If multiple outputs are required, shared facts are computed once (§5.5).
- [ ] Original source files are not modified unless the prompt requires it (§5.4).
- [ ] File paths in the code match the paths stated in the prompt.
- [ ] ICS events: DTEND computed from DURATION when absent; date objects normalised to datetime.
- [ ] CSV/XLSX numeric values: cast from string before aggregation.
- [ ] Timezone-aware datetimes: stripped to naive before comparison.

Run a quick smoke test after writing:

```bash
cd /app && python3 -c "from solve import run; run()" && cat data/answer.txt
```

For byte-level verification:
```bash
cd /app && python3 -c "
data = open('data/answer.txt','rb').read()
print('Ends with single newline:', data.endswith(b'\n') and not data.endswith(b'\n\n'))
print('Last 30 bytes:', repr(data[-30:]))
"
```
