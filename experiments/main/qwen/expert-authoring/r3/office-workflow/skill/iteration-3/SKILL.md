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

## Step 1 — Extract Parameters from the Instruction

Before writing code, identify these values from the task instruction:

| Parameter | Question to answer |
|-----------|-------------------|
| Source path + pattern | Where are the input files? (`data/emails/Bob/*.eml`) |
| Filter criteria | Which items to select? (exact subject, date range, sender) |
| Sort order | How to order selected items? (by filename, by date) |
| Output path + format | Where to write? What format? (`data/answer.txt`, block-separated TXT) |
| Exclusions | What must NOT appear in output? (distractor items) |

**Never hardcode values from one task instance.** They will differ across variants.

## Step 2 — Pick Your Strategy

| Task involves… | Section | Key library |
|----------------|---------|-------------|
| Filter emails by header → TXT/JSON | §1 Email Filtering | `email` |
| Find free time / schedule events | §2 Calendar Scheduling | `icalendar` |
| Extract data from PDF or XLSX | §3 Data Extraction | `pypdf`, `openpyxl` |
| Compute stats / draw charts | §4 Quantitative Analysis | `Pillow` |
| Summarize + create calendar events | §1 + §2 combined | `email` + `icalendar` |
| Route outputs per recipient | §5 Routing | `email`, `os` |

## Step 3 — Write solve.py

```python
def run():
    # 1. Discover and parse source artifacts
    # 2. Filter / select / schedule
    # 3. Build and write output
    ...
```

**Contract:**
- Entry point: `from solve import run; run()`
- All imports inside `solve.py`
- Write to `/app/solve.py` (no Markdown fences)
- Include self-verification at end of `run()` (see §6)

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

### Complete template

```python
import email, email.policy, glob, os, re

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

def run():
    # --- Extract from instruction (NEVER hardcode) ---
    source_dir = "data/emails/Bob"          # from instruction
    target_subjects = {"scheduled meeting", "application approved"}  # from instruction
    output_path = "data/answer.txt"         # from instruction

    # --- Discover & filter ---
    eml_files = sorted(glob.glob(os.path.join(source_dir, "*.eml")))
    selected = []
    for fpath in eml_files:
        msg = parse_eml(fpath)
        subject = msg.get("Subject", "")
        if subject in target_subjects:
            body = get_text_body(msg)
            selected.append((os.path.basename(fpath), subject, body))

    # --- Build output ---
    blocks = []
    for (fname, subject, body) in selected:
        blocks.append(f"Subject: {subject}\n{body}")
    output = "\n\n".join(blocks) + "\n"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    # --- Self-verify ---
    with open(output_path, "rb") as f:
        content = f.read()
    assert content.endswith(b"\n") and not content.endswith(b"\n\n\n")
    assert len(re.findall(rb"^Subject: ", content, re.MULTILINE)) == len(selected)
```

### Rules

- **Always** use `email.policy.default` — never the legacy parser.
- **Exact** subject match unless instruction says "contains" or "regex".
- **Sort** by the key from the instruction (default: source filename via `sorted(glob.glob(...))`).
- **Multipart**: `msg.walk()` → take first `text/plain` part.
- **Strip** body: `.strip()` on extracted content.
- **Exclude** all content from non-selected messages.
- **Output**: blocks separated by `\n\n`, file ends with exactly one `\n`.

### Inspect emails programmatically (do NOT cat raw files)

Instead of dumping raw MIME, write a quick Python inspection:

```python
import glob, email, email.policy
for f in sorted(glob.glob("data/emails/Bob/*.eml")):
    msg = email.message_from_binary_file(open(f, "rb"), policy=email.policy.default)
    print(f"{f}: Subject={msg.get('Subject')!r}, Content-Type={msg.get_content_type()}")
```

This gives you headers without noise — no need to read raw MIME boundaries.

---

## §2 Calendar Scheduling (ICS ↔ ICS / Email → ICS)

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

**Rules:**
- Use `.decoded("dtstart")` / `.decoded("dtend")` for timezone-aware datetimes.
- `TRANSP:TRANSPARENT` events do NOT block time — skip them.
- When merging calendars, **union** all busy intervals before searching.
- **Preserve** original events when modifying an existing calendar.
- Write with `cal.to_ical()` in UTF-8. Include `PRODID`, `VERSION`, `UID`.

---

## §3 Data Extraction (PDF / XLSX → JSON / TXT)

```python
from pypdf import PdfReader
def extract_pdf_text(path):
    return "\n".join(PdfReader(path).pages[i].extract_text() or ""
                     for i in range(len(PdfReader(path).pages)))

from openpyxl import load_workbook
def read_xlsx(path, sheet_name=None):
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    return [[cell.value for cell in row] for row in ws.iter_rows()]
```

**Rules:** `data_only=True` for cached values; de-duplicate rows if instructed; handle `None` cells.

---

## §4 Quantitative Analysis (XLSX → TXT + JPEG)

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

**Rules:** Text and chart summaries must **agree exactly**. Always specify format in `img.save()`.

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

**Rules:** "One per message" vs "one per recipient" — read instruction carefully. Keep individualized facts consistent across paired artifacts.

---

## §6 Self-Verification (always include)

Inline this at the end of `run()`:

```python
    # Self-verify
    with open(output_path, "rb") as f:
        content = f.read()
    assert len(content) > 0, "Output empty"
    assert content.endswith(b"\n"), "Missing trailing newline"
    assert not content.endswith(b"\n\n\n"), "Too many trailing newlines"
    import re
    count = len(re.findall(rb"^Subject: ", content, re.MULTILINE))
    assert count == len(selected), f"Expected {len(selected)} blocks, got {count}"
    # Check no excluded content leaked
    for distractor in ["Gradescope", "Reminder Rent"]:  # from instruction
        assert distractor.encode() not in content, f"Leaked: {distractor}"
```

**Checklist before returning:**
- [ ] Source files unmodified
- [ ] Cross-artifact facts agree (dates in TXT = dates in ICS)
- [ ] Individualized facts consistent across paired outputs
- [ ] Original calendar events preserved (if modifying ICS)
- [ ] Extracted bodies are complete, stripped, not truncated

---

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Legacy email parser | `email.message_from_binary_file(f, policy=email.policy.default)` |
| Missing `.strip()` | Always strip extracted text bodies |
| Wrong sort key | Extract from instruction; default to filename |
| Content leaked | Filter: `subject in target_set` (exact match) |
| Trailing newlines | `"\n\n".join(blocks) + "\n"`; verify with `repr()` |
| Cat raw MIME wastes turns | Use programmatic header inspection (see §1) |
| `xxd` not available | Use `python3 -c "..."` for byte inspection |
| Calendar tz mismatch | Always use `.decoded()` |
| XLSX → `None` | `data_only=True` in `load_workbook` |
| Hardcoded values | Read all parameters from the task instruction |
