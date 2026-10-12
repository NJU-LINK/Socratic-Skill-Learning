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

## Environment Inventory

Available libraries (verify with `pip list` if unsure):

| Library       | Use                                            |
|---------------|------------------------------------------------|
| `email` (stdlib) | Parse / construct MIME `.eml` files         |
| `icalendar`   | Read / write / modify `.ics` calendars         |
| `openpyxl`    | Read / write `.xlsx` spreadsheets              |
| `python-docx` | Create / modify `.docx` documents              |
| `pypdf`       | Read / merge / split PDFs                      |
| `reportlab`   | Generate PDFs from scratch                     |
| `Pillow`      | Image manipulation, chart → JPEG/PNG           |
| stdlib        | `json`, `csv`, `glob`, `re`, `os`, `datetime`, `collections` |

Always `import` inside `solve.py`; never assume site-packages are pre-imported.

---

## General Solve Pattern

Every task in this family follows **Read → Decide → Transform → Write**:

```python
import os, glob

def run():
    # 1. Discover source artifacts
    # 2. Parse each artifact with the correct library
    # 3. Apply selection / routing / scheduling logic
    # 4. Build output artifacts (text, calendar, spreadsheet, image, etc.)
    # 5. Write outputs to exact paths with exact formatting
    ...
```

The `run()` function is the single entry point. Tests call `from solve import run; run()`.

---

## Strategy by Workflow Relation

### 1. Relevance Filtering (Email → Text/JSON)

**When:** Select messages whose headers match a whitelist / blacklist.

```python
import email, email.policy

def parse_eml(path):
    with open(path, "rb") as f:
        return email.message_from_binary_file(f, policy=email.policy.default)

def get_text_body(msg):
    """Return the decoded, stripped plain-text body from a MIME message."""
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

**Key rules:**
- Use `email.policy.default` (not legacy) to get proper header decoding.
- Subject matching is **exact** unless the task says "contains" or "matches regex".
- Sort selected messages by **source filename** (lexicographic on `os.path.basename`).
- For multi-part messages, walk parts and take the first `text/plain` part.

### 2. Conflict-Free Scheduling (Calendar / Email → ICS)

**When:** Find common free time across multiple calendars or schedule events without overlap.

```python
from icalendar import Calendar, Event
from datetime import datetime, timedelta

def load_ics(path):
    with open(path, "rb") as f:
        return Calendar.from_ical(f.read())

def get_busy_intervals(cal):
    """Return sorted list of (start, end) datetime tuples from VEVENT components."""
    intervals = []
    for comp in cal.walk():
        if comp.name == "VEVENT":
            start = comp.decoded("dtstart")
            end   = comp.decoded("dtend")
            intervals.append((start, end))
    return sorted(intervals, key=lambda iv: iv[0])

def find_free_slots(busy_intervals, window_start, window_end, duration):
    """Yield start times for `duration`-timedelta slots free within the window."""
    cursor = window_start
    for (bs, be) in busy_intervals:
        if cursor + duration <= bs:
            while cursor + duration <= min(bs, window_end):
                yield cursor
                cursor += duration
        cursor = max(cursor, be)
    while cursor + duration <= window_end:
        yield cursor
        cursor += duration
```

**Key rules:**
- Decode `dtstart`/`dtend` with `.decoded()` to get timezone-aware datetimes.
- "Public" or "free" transparency events (`TRANSP:TRANSPARENT`) do NOT block time.
- When merging multiple calendars, union all busy intervals before searching.
- Write output with `Calendar.to_ical()` and UTF-8 encoding.

### 3. Fact / Table Extraction (PDF / XLSX → JSON / TXT)

**When:** Pull structured data from PDFs or spreadsheets.

```python
# PDF text extraction
from pypdf import PdfReader

def extract_pdf_text(path):
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)

# XLSX reading
from openpyxl import load_workbook

def read_xlsx_table(path, sheet_name=None):
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    return [[cell.value for cell in row] for row in ws.iter_rows()]
```

**Key rules:**
- `data_only=True` returns cached formula values, not the formula string.
- De-duplicate rows when the task mentions duplicate source rows.
- For PDFs with tables, `pypdf` text extraction + regex parsing is usually sufficient; fall back to manual coordinate-based extraction only if needed.

### 4. Quantitative Analysis & Visualization (XLSX → TXT + JPEG)

**When:** Compute summary statistics and produce charts.

```python
from collections import Counter
from PIL import Image, ImageDraw

def basic_stats(values):
    n = len(values)
    mean = sum(values) / n
    sorted_v = sorted(values)
    median = sorted_v[n // 2] if n % 2 else (sorted_v[n//2 - 1] + sorted_v[n//2]) / 2
    return {"count": n, "mean": mean, "median": median,
            "min": min(values), "max": max(values)}

def simple_bar_chart(data_dict, path, width=600, height=400):
    """Draw a horizontal bar chart and save as JPEG."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    if not data_dict:
        img.save(path, "JPEG")
        return
    max_val = max(data_dict.values())
    bar_h = (height - 40) // len(data_dict)
    for i, (label, val) in enumerate(data_dict.items()):
        y = 20 + i * bar_h
        bar_w = int((width - 150) * val / max_val) if max_val else 0
        draw.rectangle([120, y, 120 + bar_w, y + bar_h - 4], fill="steelblue")
        draw.text((5, y + bar_h // 2 - 6), str(label), fill="black")
    img.save(path, "JPEG")
```

**Key rules:**
- Ensure quantitative summaries in text output and chart output **agree exactly** (same count, same mean).
- Use `Pillow` for chart generation when matplotlib is unavailable.
- Always save charts with explicit format: `img.save(path, "JPEG")` or `"PNG"`.

### 5. Summarization + Scheduling (Email → TXT + ICS)

Combine strategies 1 and 2: extract facts from emails, then create calendar events from those facts. Ensure dates mentioned in the summary text match the `DTSTART`/`DTEND` in the ICS output.

### 6. Recipient-Based Routing & Format Conversion

**When:** Route outputs to per-recipient folders or convert formats per recipient.

```python
def route_by_recipient(msg, base_dir):
    to_addr = msg.get("To", "")
    # Derive folder name from recipient
    name = to_addr.split("@")[0] if "@" in to_addr else to_addr
    out_dir = os.path.join(base_dir, name)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir
```

**Key rules:**
- One output per message vs. one output per recipient: read the task carefully.
- When generating per-recipient PDFs and emails, ensure **individualized facts** (name, amount, date) are consistent across both artifacts.

---

## Output Formatting Rules

### TXT output
- Separate logical blocks with **one blank line** (`\n\n` between blocks).
- End the file with **exactly one trailing newline** (`\n`).
- Strip bodies: remove leading/trailing whitespace from extracted text.
- Do NOT include any content from non-selected messages.

### ICS output
- Begin with `BEGIN:VCALENDAR` and end with `END:VCALENDAR`.
- Include `PRODID` and `VERSION` properties.
- Use `UID` for each event (can generate with `uuid.uuid4()`).

### JSON output
- Use `json.dumps(data, indent=2, ensure_ascii=False)` for readable output.
- Always end with a trailing newline.

---

## Preservation & Consistency Checklist

Before finalizing outputs, verify:

1. **Original source artifacts are unmodified** — never overwrite input files.
2. **Cross-artifact fact agreement** — if a date appears in both a TXT summary and an ICS event, the values must match.
3. **Individualized facts in paired outputs** — when generating per-recipient PDF + email, the name/amount/date in the PDF must match those in the email body.
4. **Calendar preservation** — when updating an existing calendar, all original events must remain intact unless explicitly told to remove.
5. **Selected content fidelity** — extracted email bodies must be the complete plain-text content (stripped), not a truncated or paraphrased version.

---

## Self-Verification Checklist

After `run()` completes, validate before returning:

```python
def _verify():
    """Optional self-check — call at end of run() if desired."""
    # 1. Output file exists
    assert os.path.exists("data/answer.txt"), "Output file missing"
    # 2. File ends with exactly one newline
    with open("data/answer.txt", "rb") as f:
        content = f.read()
    assert content.endswith(b"\n"), "Missing trailing newline"
    assert not content.endswith(b"\n\n\n"), "Too many trailing newlines"
    # 3. No content from non-selected messages leaked
    # 4. Block count matches expected selected message count
```

**Runtime verification approach:**
- Re-parse output file and count blocks → must equal number of selected sources.
- For each block, re-extract the Subject line and verify it matches a target subject.
- For scheduling outputs, reload the generated ICS and verify no event overlaps.
- For quantitative outputs, recompute one statistic from raw data and compare to written value.

---

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Using `email.message_from_file()` (legacy) | Use `email.message_from_binary_file(f, policy=email.policy.default)` |
| Forgetting `.strip()` on extracted body | Always strip leading/trailing whitespace from text bodies |
| Sorting by email Date header instead of filename | Use `sorted(glob.glob(...))` on full paths or basenames |
| Including non-matching messages | Use exact set membership: `subject in target_set` |
| Multi-part body extraction misses nested parts | Use `msg.walk()` and take first `text/plain` part |
| Off-by-one in trailing newlines | Write `"\n".join(blocks) + "\n"` pattern; verify with `repr(content)` |
| Calendar timezone mismatches | Always use `.decoded()` and compare like with like |
| XLSX formula cells returning `None` | Use `data_only=True` in `load_workbook` |
