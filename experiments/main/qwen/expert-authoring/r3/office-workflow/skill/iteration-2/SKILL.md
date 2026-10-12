---
name: office-workflow
description: >
  Automate multi-artifact office workflows that read, filter, transform, and
  route content across MIME email (.eml), iCalendar (.ics), spreadsheets
  (.xlsx), PDF, and images. Covers subject/recipient-based filtering, body
  extraction, conflict-free scheduling, quantitative analysis, format
  conversion, and cross-artifact consistency preservation.
---

# Office Workflow Automation

## Task Decomposition — Do This First

Before writing any code, extract these parameters from the task instruction:

| Parameter | Example values | Where to find it |
|-----------|---------------|------------------|
| **Source path** | `data/emails/Bob/`, `data/calendar.ics` | Instruction text |
| **Source pattern** | `*.eml`, `*.ics`, `*.xlsx`, `*.pdf` | Instruction text |
| **Filter criteria** | Exact subject match, date range, sender, class | Instruction text |
| **Sort order** | By filename, by date, by recipient | Instruction text |
| **Output path** | `data/answer.txt`, `data/out.ics` | Instruction text |
| **Output format** | Block-separated TXT, ICS, JSON, DOCX, JPEG | Instruction text |
| **Exclusions** | Which items to skip, distractors to reject | Instruction text |

**Never hardcode values from one task instance.** Always read them from the actual instruction at runtime. The paths, subjects, dates, and format rules will differ across variants.

## Quick Strategy Router

Use this table to find the right strategy for your task:

| Task involves… | Strategy | Key library |
|----------------|----------|-------------|
| Filter emails by header → TXT/JSON | §1 Email Filtering | `email` |
| Find free time / schedule events | §2 Calendar Scheduling | `icalendar` |
| Extract data from PDF or XLSX | §3 Data Extraction | `pypdf`, `openpyxl` |
| Compute stats / draw charts | §4 Quantitative Analysis | `Pillow`, stdlib |
| Summarize + create calendar events | §1 + §2 combined | `email` + `icalendar` |
| Route outputs per recipient | §5 Routing | `email`, `os` |

## Solve Contract

Every solution follows this pattern:

```python
def run():
    # 1. Read the instruction to extract parameters (paths, criteria, format)
    # 2. Discover and parse source artifacts with the correct library
    # 3. Apply selection / transformation / scheduling logic
    # 4. Write output artifacts to the exact specified paths
    ...
```

- Entry point: `from solve import run; run()`
- All imports must be inside `solve.py`.
- Write to `/app/solve.py` (not wrapped in Markdown fences).

## Available Libraries

| Library | Import | Use |
|---------|--------|-----|
| `email` (stdlib) | `import email, email.policy` | Parse/construct `.eml` |
| `icalendar` | `from icalendar import Calendar, Event` | Read/write `.ics` |
| `openpyxl` | `from openpyxl import load_workbook` | Read/write `.xlsx` |
| `python-docx` | `from docx import Document` | Create/modify `.docx` |
| `pypdf` | `from pypdf import PdfReader` | Read/merge PDFs |
| `reportlab` | `from reportlab.lib.pagesizes import letter` | Generate PDFs |
| `Pillow` | `from PIL import Image, ImageDraw` | Image/chart generation |
| stdlib | `json, csv, glob, re, os, datetime, collections, uuid` | General utilities |

---

## §1 Email Filtering (Email → TXT / JSON)

### Parse .eml files

```python
import email, email.policy, glob, os

def parse_eml(path):
    with open(path, "rb") as f:
        return email.message_from_binary_file(f, policy=email.policy.default)

def get_text_body(msg):
    """Decoded, stripped plain-text body from a MIME message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                content = part.get_content()
                if isinstance(content, bytes):
                    content = content.decode(part.get_content_charset() or "utf-8")
                return content.strip()
    else:
        content = msg.get_content()
        if isinstance(content, bytes):
            content = content.decode(msg.get_content_charset() or "utf-8")
        return content.strip()
    return ""
```

### Rules

- **Always** use `email.policy.default` — never the legacy parser.
- **Exact** subject match unless instruction says "contains" or "regex".
- **Sort** by the key specified in the instruction (default: source filename via `sorted(glob.glob(...))`).
- **Multipart**: walk parts, take the first `text/plain` part.
- **Strip** body text: `.strip()` on the extracted content.
- **Exclude** all content from non-selected messages — no headers, no bodies.

### Output formatting (TXT blocks)

```python
blocks = []
for (filename, subject, body) in selected:
    blocks.append(f"Subject: {subject}\n{body}")

output = "\n\n".join(blocks) + "\n"   # one blank line between blocks, one trailing \n
```

- Separate adjacent blocks with **one blank line**.
- File ends with **exactly one** trailing newline.
- Verify with `repr(content)` to check for extra whitespace.

---

## §2 Calendar Scheduling (ICS ↔ ICS / Email → ICS)

### Load and inspect calendars

```python
from icalendar import Calendar

def load_ics(path):
    with open(path, "rb") as f:
        return Calendar.from_ical(f.read())

def get_events(cal):
    events = []
    for comp in cal.walk():
        if comp.name == "VEVENT":
            events.append({
                "summary": str(comp.get("summary", "")),
                "start": comp.decoded("dtstart"),
                "end": comp.decoded("dtend"),
                "transp": str(comp.get("transp", "OPAQUE")),
            })
    return events
```

### Find free slots

```python
def find_free_slots(busy_intervals, window_start, window_end, duration):
    """Yield start datetimes for duration-timedelta slots free in window."""
    cursor = window_start
    for (bs, be) in sorted(busy_intervals):
        if cursor + duration <= bs:
            while cursor + duration <= min(bs, window_end):
                yield cursor
                cursor += duration
        cursor = max(cursor, be)
    while cursor + duration <= window_end:
        yield cursor
        cursor += duration
```

### Rules

- Use `.decoded("dtstart")` / `.decoded("dtend")` for timezone-aware datetimes.
- `TRANSP:TRANSPARENT` events do NOT block time — skip them.
- When merging calendars, **union** all busy intervals before searching.
- **Preserve** original events when modifying an existing calendar.
- Write with `cal.to_ical()` in UTF-8. Include `PRODID`, `VERSION`, and `UID` per event.

---

## §3 Data Extraction (PDF / XLSX → JSON / TXT)

```python
from pypdf import PdfReader

def extract_pdf_text(path):
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)

from openpyxl import load_workbook

def read_xlsx(path, sheet_name=None):
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    return [[cell.value for cell in row] for row in ws.iter_rows()]
```

### Rules

- `data_only=True` returns cached formula values, not formula strings.
- **De-duplicate** rows when instruction mentions duplicates.
- For PDF tables, `pypdf` + regex parsing is usually sufficient.
- Handle `None` cells from empty XLSX rows.

---

## §4 Quantitative Analysis & Visualization (XLSX → TXT + JPEG)

```python
from PIL import Image, ImageDraw

def simple_bar_chart(data_dict, path, width=600, height=400):
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    if not data_dict:
        img.save(path, "JPEG"); return
    max_val = max(data_dict.values()) or 1
    bar_h = (height - 40) // len(data_dict)
    for i, (label, val) in enumerate(data_dict.items()):
        y = 20 + i * bar_h
        bar_w = int((width - 150) * val / max_val)
        draw.rectangle([120, y, 120 + bar_w, y + bar_h - 4], fill="steelblue")
        draw.text((5, y + bar_h // 2 - 6), str(label), fill="black")
    img.save(path, "JPEG")
```

### Rules

- Quantitative summaries in text and chart outputs must **agree exactly**.
- Save charts with explicit format: `img.save(path, "JPEG")` or `"PNG"`.
- Handle edge cases: empty data, zero values, single data point.

---

## §5 Recipient-Based Routing

```python
def route_by_recipient(msg, base_dir):
    to_addr = msg.get("To", "")
    name = to_addr.split("@")[0] if "@" in to_addr else to_addr
    out_dir = os.path.join(base_dir, name)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir
```

### Rules

- **One output per message** vs **one output per recipient**: read instruction carefully.
- Individualized facts (name, amount, date) must be consistent across paired artifacts.

---

## Output Format Quick Reference

| Format | Key rules |
|--------|-----------|
| **TXT** | Blocks separated by `\n\n`; file ends with exactly one `\n`; strip bodies |
| **ICS** | `BEGIN:VCALENDAR` … `END:VCALENDAR`; include `PRODID`, `VERSION`, `UID` |
| **JSON** | `json.dumps(data, indent=2, ensure_ascii=False) + "\n"` |
| **DOCX** | Use `Document()` → `.add_paragraph()` → `.save(path)` |
| **JPEG/PNG** | Always specify format string in `img.save()` |

---

## Self-Verification

After `run()`, validate before returning:

```python
import os

# 1. Output file exists and is non-empty
assert os.path.exists(output_path), "Output missing"
with open(output_path, "rb") as f:
    content = f.read()
assert len(content) > 0, "Output is empty"

# 2. Trailing newline check (for text outputs)
assert content.endswith(b"\n"), "Missing trailing newline"
assert not content.endswith(b"\n\n\n"), "Too many trailing newlines"

# 3. No excluded content leaked
# (check that distractor identifiers don't appear in output)

# 4. Block count matches expected selection count
import re
subject_count = len(re.findall(rb"^Subject: ", content, re.MULTILINE))
assert subject_count == len(selected), f"Expected {len(selected)} blocks, got {subject_count}"
```

### Checklist

- [ ] Source files unmodified (never overwrite inputs)
- [ ] Cross-artifact facts agree (dates in TXT = dates in ICS)
- [ ] Individualized facts consistent across paired outputs
- [ ] Original calendar events preserved (if modifying existing ICS)
- [ ] Extracted bodies are complete, stripped, not truncated

---

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Legacy email parser | Use `email.message_from_binary_file(f, policy=email.policy.default)` |
| Missing `.strip()` on body | Always strip extracted text |
| Wrong sort key | Extract sort requirement from instruction; default to filename |
| Non-matching content leaked | Filter with exact set: `subject in target_set` |
| Off-by-one trailing newlines | `"\n\n".join(blocks) + "\n"`; verify with `repr()` |
| `xxd` not available | Use `python3 -c "..."` for byte inspection |
| Calendar timezone mismatch | Always use `.decoded()` |
| XLSX formulas → `None` | `data_only=True` in `load_workbook` |
| Hardcoded v01 values | Read all parameters from the task instruction |
