---
name: office-workflow
description: >
  Generalized methods for office workflow automation tasks that read, transform,
  and write office artifacts (email, calendar, PDF, XLSX, DOCX, TXT, JSON, ICS,
  JPEG, EML, PDF). Covers source parsing, workflow relations (filtering,
  scheduling, extraction, analysis, summarization, routing), output formatting,
  temporal/routing constraints, and cross-output preservation and consistency.
---

# Office Workflow Skill

This skill covers the family of office workflow automation tasks defined by the spec. Each section provides concrete, runnable code patterns grounded in v01 experience and extrapolated to other family members.

## 0. Task Analysis & Recipe Selection (READ FIRST)

**Core Principle**: Write code from the task spec first. Trust the parser for structural concerns. Inspect source data only when:
   - (a) your code fails or produces unexpected output,
   - (b) the task requires understanding content format not specified in the task description (e.g., date formats, table layouts), or
   - (c) you need to discover the schema (e.g., XLSX column names that the task doesn't list).

For most tasks (like v01), none of these exceptions apply, so write code directly without inspection.

### 0.0 Decision Checklist: Do I Need to Inspect?

Before inspecting any source file, check each item. If ALL answers are "yes, the spec tells me", do NOT inspect.

| Question | If task spec says... | Then... |
|----------|---------------------|---------|
| What files to read? | Exact path (e.g., `data/emails/Bob/`) | Don't `ls` the directory |
| What to filter/select? | Exact criteria (e.g., subject = "X" or "Y") | Don't inspect subjects/content |
| What format to output? | Exact format (e.g., "Subject: <subject>\n<body>") | Don't verify with multiple methods |
| What columns/fields exist? | Exact names (e.g., "revenue", "quantity") | Don't inspect schema |
| What date/time format? | Exact format (e.g., "YYYY-MM-DD") | Don't inspect date strings |

**Only inspect when the answer to one of these is "the spec doesn't say".**

**Example: v01 task**
- What files to read? → `data/emails/Bob/*.eml` ✅ (spec says exact path)
- What to filter? → Subject exactly "scheduled meeting" or "application approved" ✅ (spec says exact strings)
- What format to output? → `Subject: <subject>\n<body>`, blocks separated by blank line ✅ (spec says exact format)
- All answers are "yes, the spec tells me" → **DO NOT INSPECT. Write code directly.**

### 0.1 Task Analysis Steps

1. **Identify artifact types** (input → output):
   - Input: .eml, .ics, .pdf, .xlsx, or combinations
   - Output: .txt, .ics, .json, .docx, .pdf, .eml, .jpeg

2. **Identify workflow relation**:
   - Relevance filtering (select by criteria)
   - Conflict-free scheduling (find common free time)
   - Fact/table extraction (parse structured data)
   - Quantitative analysis (compute statistics)
   - Summarization (condense content)
   - Notification/routing (send to recipients)

3. **Select patterns from this SKILL**:
   - §2 Source Parsing → match input artifact type
   - §3 Workflow Relations → match the relation
   - §4 Output Formatting → match output artifact type
   - §5 Routing → if multiple outputs needed

4. **Write code directly** using the patterns. Inspect source files only when:
   - (a) your code fails or produces unexpected output,
   - (b) the task requires understanding content format not in the spec (e.g., date formats, table layouts), or
   - (c) you need to discover the schema (e.g., XLSX column names).

**Example Recipe** (v01: filter emails → write TXT):
```python
# 1. Parse emails (SKILL §2.1)
for eml_path in sorted(emails_dir.glob("*.eml")):
    msg = email.message_from_binary_file(f, policy=policy.default)
    subject = msg["Subject"]
    
    # 2. Filter (SKILL §3.1)
    if subject in target_subjects:
        body = extract_text_body(msg)
        selected.append((subject, body))

# 3. Format output (SKILL §4.1)
blocks = [f"Subject: {s}\n{b}" for s, b in selected]
write_txt(output_path, blocks)
```

**Why this matters**: Manual inspection wastes tool calls and doesn't scale. The parsers in §2 handle all edge cases (multipart, encoding, etc.). Trust them.

## 0.2 Complete End-to-End Recipes

### Recipe A: Filter Emails → Write TXT (v01 pattern)
```python
import email
from email import policy
from pathlib import Path

_BASE = Path(__file__).resolve().parent

def run():
    emails_dir = _BASE / "data" / "emails" / "Bob"
    output_path = _BASE / "data" / "answer.txt"
    target_subjects = {"scheduled meeting", "application approved"}
    
    selected = []
    for eml_path in sorted(emails_dir.glob("*.eml")):
        with open(eml_path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        
        subject = msg["Subject"]
        if subject in target_subjects:
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_content()
                        if isinstance(payload, str):
                            body = payload
                            break
            else:
                body = msg.get_content()
            
            selected.append((eml_path.name, subject, body.strip()))
    
    blocks = [f"Subject: {s}\n{b}" for _, s, b in selected]
    output = "\n\n".join(blocks) + "\n"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(output)

if __name__ == "__main__":
    run()
```

### Recipe B: Extract Calendar Events → Write JSON
```python
from icalendar import Calendar
from pathlib import Path
import json

_BASE = Path(__file__).resolve().parent

def run():
    ics_path = _BASE / "data" / "calendar.ics"
    output_path = _BASE / "data" / "events.json"
    
    with open(ics_path, "rb") as f:
        cal = Calendar.from_ical(f.read())
    
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            events.append({
                "summary": str(component.get("SUMMARY", "")),
                "start": str(component.get("DTSTART").dt),
                "end": str(component.get("DTEND").dt) if component.get("DTEND") else None
            })
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(events, f, indent=2, default=str)

if __name__ == "__main__":
    run()
```

### Recipe C: Parse XLSX → Compute Stats → Write TXT Summary
```python
from openpyxl import load_workbook
from pathlib import Path

_BASE = Path(__file__).resolve().parent

def run():
    xlsx_path = _BASE / "data" / "sales.xlsx"
    output_path = _BASE / "data" / "summary.txt"
    
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    
    rows = list(ws.iter_rows(values_only=True))
    headers = [str(h) for h in rows[0]]
    data = [dict(zip(headers, row)) for row in rows[1:]]
    wb.close()
    
    # Compute stats for numeric columns
    stats = []
    for col in ["revenue", "quantity"]:
        values = [float(row[col]) for row in data if row.get(col)]
        stats.append(f"{col}: mean={sum(values)/len(values):.2f}, total={sum(values):.2f}")
    
    output = "Sales Summary\n" + "\n".join(stats) + "\n"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(output)

if __name__ == "__main__":
    run()
```

## 1. Foundation: Path Anchoring

**Invariant**: All file paths must be anchored to the script's location, not CWD. Tests may invoke `run()` from any directory.

```python
from pathlib import Path

_BASE = Path(__file__).resolve().parent

def run():
    input_dir = _BASE / "data" / "emails" / "Bob"
    output_path = _BASE / "data" / "answer.txt"
    # All paths use _BASE as prefix
```

**Why**: If a test runner changes CWD before calling `run()`, relative paths like `Path("data/...")` break. `__file__` anchors to the script's actual location.

## 2. Source Artifact Parsing

### 2.1 MIME Email (.eml)

**Pattern**: Use `email.message_from_binary_file()` with `policy.default` for automatic RFC 2047 header decoding and proper multipart handling.

```python
import email
from email import policy
from pathlib import Path

def parse_eml(eml_path: Path):
    """Parse .eml file and extract subject + plain-text body."""
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    
    # policy.default auto-decodes RFC 2047 encoded words in headers
    subject = msg["Subject"]  # Returns decoded string
    
    # Extract plain-text body from multipart or single-part message
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_content()
                if isinstance(payload, str):  # policy.default returns str for text/*
                    body = payload
                    break  # Take first text/plain part
    else:
        body = msg.get_content()
    
    return subject, body.strip()
```

**Edge cases**:
- **multipart/alternative**: The `walk()` + first-text/plain approach correctly picks plain text over HTML when both exist.
- **HTML-only emails**: If no `text/plain` part exists, `body` remains empty. Fall back to HTML extraction:
  ```python
  from html.parser import HTMLParser
  
  class HTMLTextExtractor(HTMLParser):
      def __init__(self):
          super().__init__()
          self.text = []
      def handle_data(self, data):
          self.text.append(data)
  
  def html_to_text(html: str) -> str:
      extractor = HTMLTextExtractor()
      extractor.feed(html)
      return " ".join(extractor.text).strip()
  
  # In parse_eml, if no text/plain found:
  for part in msg.walk():
      if part.get_content_type() == "text/html":
          body = html_to_text(part.get_content())
          break
  ```
- **Multiple text/plain parts**: Forwarded messages with inline replies may have multiple text/plain parts. For most workflows, take the first. For concatenation, collect all and join with `\n\n`.

### 2.2 iCalendar (.ics)

**Pattern**: Use `icalendar` library. Parse with `Calendar.from_ical()`, iterate events.

```python
from icalendar import Calendar
from pathlib import Path
from datetime import datetime

def parse_ics(ics_path: Path):
    """Parse .ics file and extract events."""
    with open(ics_path, "rb") as f:
        cal = Calendar.from_ical(f.read())
    
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            summary = component.get("SUMMARY")
            dtstart = component.get("DTSTART")
            dtend = component.get("DTEND")
            
            # Convert vDDDTypes to Python datetime
            start = dtstart.dt if dtstart else None
            end = dtend.dt if dtend else None
            
            events.append({
                "summary": str(summary) if summary else "",
                "start": start,
                "end": end,
                "description": str(component.get("DESCRIPTION", "")),
                "location": str(component.get("LOCATION", ""))
            })
    
    return events
```

**Notes**:
- `dtstart.dt` returns `datetime.date` for all-day events, `datetime.datetime` for timed events. Check type with `isinstance(dt, datetime.datetime)`.
- Timezone-aware datetimes: `icalendar` preserves tzinfo. Convert to UTC with `dt.astimezone(timezone.utc)` if needed for comparison.

### 2.3 PDF

**Pattern**: Use `pypdf` (not `PyPDF2`, which is deprecated). Extract text from each page.

```python
from pypdf import PdfReader
from pathlib import Path

def parse_pdf(pdf_path: Path):
    """Extract text from all pages of a PDF."""
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        pages.append(text)
    return "\n\n".join(pages)
```

**Notes**:
- `extract_text()` returns a string. Quality varies by PDF generation method.
- For tables, consider `pdfplumber` (if available) or parse structured text manually.
- PDF metadata: `reader.metadata` provides `/Title`, `/Author`, etc.

### 2.4 XLSX

**Pattern**: Use `openpyxl` for reading Excel files. Access sheets, rows, cells.

```python
from openpyxl import load_workbook
from pathlib import Path

def parse_xlsx(xlsx_path: Path, sheet_name: str = None):
    """Parse .xlsx file and return rows as list of dicts."""
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    
    # Select sheet
    if sheet_name:
        ws = wb[sheet_name]
    else:
        ws = wb.active  # First sheet
    
    # Convert to list of dicts (header row as keys)
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    
    headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    data = []
    for row in rows[1:]:
        record = dict(zip(headers, row))
        data.append(record)
    
    wb.close()
    return data
```

**Notes**:
- `read_only=True` is faster for large files.
- `data_only=True` returns calculated values instead of formulas.
- For multiple sheets: `wb.sheetnames` lists all sheet names.

## 3. Workflow Relations

### 3.1 Relevance Filtering

**Pattern**: Select artifacts based on header/content criteria. Common in v01: filter emails by exact subject match.

```python
def filter_by_subject(emails: list, target_subjects: set):
    """Filter emails by exact subject match."""
    selected = []
    for eml_path, subject, body in emails:
        if subject in target_subjects:
            selected.append((eml_path, subject, body))
    return selected

# Usage:
target_subjects = {"scheduled meeting", "application approved"}
selected = filter_by_subject(all_emails, target_subjects)
```

**Variations**:
- **Partial match**: `if any(keyword in subject for keyword in keywords)`
- **Header-based**: Filter by `From`, `To`, `Date` using similar logic.
- **Content-based**: Filter by body content with regex or keyword matching.

### 3.2 Conflict-Free Scheduling

**Pattern**: Find common free-time windows across multiple calendars.

```python
from datetime import datetime, timedelta

def find_free_time(calendars: list, duration_minutes: int, start_hour: int = 9, end_hour: int = 17):
    """Find common free slots across multiple calendars."""
    # Collect all busy times
    busy_times = []
    for events in calendars:
        for event in events:
            if event["start"] and event["end"]:
                busy_times.append((event["start"], event["end"]))
    
    # Sort by start time
    busy_times.sort(key=lambda x: x[0])
    
    # Find gaps
    free_slots = []
    current_time = datetime.now().replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end_time = current_time.replace(hour=end_hour)
    
    for busy_start, busy_end in busy_times:
        if current_time < busy_start:
            gap_minutes = (busy_start - current_time).total_seconds() / 60
            if gap_minutes >= duration_minutes:
                free_slots.append((current_time, busy_start))
        current_time = max(current_time, busy_end)
    
    # Check final gap
    if current_time < end_time:
        gap_minutes = (end_time - current_time).total_seconds() / 60
        if gap_minutes >= duration_minutes:
            free_slots.append((current_time, end_time))
    
    return free_slots
```

### 3.3 Fact/Table Extraction

**Pattern**: Extract structured data from unstructured text (PDF, email body).

```python
import re

def extract_dates(text: str):
    """Extract dates from text using regex."""
    # Match common date formats
    patterns = [
        r'\b\d{4}-\d{2}-\d{2}\b',  # 2024-01-15
        r'\b\d{2}/\d{2}/\d{4}\b',  # 01/15/2024
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w* \d{1,2},? \d{4}\b'  # January 15, 2024
    ]
    
    dates = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        dates.extend(matches)
    
    return dates

def extract_table_from_text(text: str):
    """Extract tabular data from structured text (e.g., PDF tables)."""
    lines = text.strip().split('\n')
    # Detect table structure (simplified)
    table = []
    for line in lines:
        if '\t' in line or '  ' in line:
            row = [cell.strip() for cell in re.split(r'\t|  +', line)]
            table.append(row)
    return table
```

### 3.4 Quantitative Analysis

**Pattern**: Compute statistics from tabular data (XLSX, extracted tables).

```python
def compute_statistics(data: list, numeric_columns: list):
    """Compute basic statistics for numeric columns."""
    stats = {}
    for col in numeric_columns:
        values = [row[col] for row in data if row.get(col) is not None]
        values = [float(v) for v in values if isinstance(v, (int, float, str)) and v.replace('.', '').replace('-', '').isdigit()]
        
        if values:
            stats[col] = {
                "count": len(values),
                "sum": sum(values),
                "mean": sum(values) / len(values),
                "min": min(values),
                "max": max(values)
            }
    
    return stats
```

### 3.5 Summarization

**Pattern**: Generate concise summaries from long text (email bodies, PDF content).

```python
def summarize_text(text: str, max_sentences: int = 3):
    """Extract key sentences as a summary."""
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    # Simple heuristic: take first N sentences
    summary = ". ".join(sentences[:max_sentences]) + "."
    return summary
```

### 3.6 Notification/Routing

**Pattern**: Route outputs to recipients based on criteria (recipient identity, subject, class membership).

```python
def route_by_recipient(items: list, recipient_field: str):
    """Group items by recipient."""
    from collections import defaultdict
    routed = defaultdict(list)
    
    for item in items:
        recipient = item.get(recipient_field)
        if recipient:
            routed[recipient].append(item)
    
    return dict(routed)
```

## 4. Destination Artifact Formatting

### 4.1 TXT

**Pattern**: Write structured text with blocks separated by blank lines.

```python
def write_txt(output_path: Path, blocks: list):
    """Write blocks to TXT file with blank-line separators."""
    # Each block is a string
    output = "\n\n".join(blocks) + "\n"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(output)

# Usage (v01 pattern):
blocks = []
for fname, subject, body in selected_emails:
    block = f"Subject: {subject}\n{body}"
    blocks.append(block)

write_txt(_BASE / "data" / "answer.txt", blocks)
```

**Format rules**:
- Separate blocks with one blank line (`\n\n`).
- End file with one newline.
- Strip leading/trailing whitespace from each block's content.

### 4.2 ICS

**Pattern**: Generate iCalendar events using `icalendar`.

```python
from icalendar import Calendar, Event
from datetime import datetime

def write_ics(output_path: Path, events: list):
    """Write events to .ics file."""
    cal = Calendar()
    cal.add("prodid", "-//Office Workflow//EN")
    cal.add("version", "2.0")
    
    for event_data in events:
        event = Event()
        event.add("summary", event_data["summary"])
        event.add("dtstart", event_data["start"])
        event.add("dtend", event_data["end"])
        if event_data.get("description"):
            event.add("description", event_data["description"])
        if event_data.get("location"):
            event.add("location", event_data["location"])
        
        cal.add_component(event)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(cal.to_ical())
```

### 4.3 JSON

**Pattern**: Write structured data as JSON.

```python
import json

def write_json(output_path: Path, data):
    """Write data to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)  # default=str handles datetime
```

**Notes**:
- `default=str` converts datetime objects to ISO format strings.
- Use `indent=2` for readable output.

### 4.4 DOCX

**Pattern**: Generate Word documents using `python-docx`.

```python
from docx import Document
from pathlib import Path

def write_docx(output_path: Path, sections: list):
    """Write sections to .docx file."""
    doc = Document()
    
    for section in sections:
        if section["type"] == "heading":
            doc.add_heading(section["text"], level=section.get("level", 1))
        elif section["type"] == "paragraph":
            doc.add_paragraph(section["text"])
        elif section["type"] == "table":
            table = doc.add_table(rows=1, cols=len(section["headers"]))
            hdr_cells = table.rows[0].cells
            for i, header in enumerate(section["headers"]):
                hdr_cells[i].text = header
            for row_data in section["rows"]:
                row_cells = table.add_row().cells
                for i, value in enumerate(row_data):
                    row_cells[i].text = str(value)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
```

### 4.5 PDF

**Pattern**: Generate PDFs using `reportlab`.

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from pathlib import Path

def write_pdf(output_path: Path, text_lines: list):
    """Write text lines to PDF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(output_path, pagesize=letter)
    width, height = letter
    
    y_position = height - 50  # Start near top
    for line in text_lines:
        c.drawString(50, y_position, line)
        y_position -= 20
        if y_position < 50:  # New page if near bottom
            c.showPage()
            y_position = height - 50
    
    c.save()
```

### 4.6 EML

**Pattern**: Generate MIME email messages.

```python
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

def write_eml(output_path: Path, subject: str, body: str, from_addr: str, to_addr: str):
    """Write email to .eml file."""
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    
    msg.attach(MIMEText(body, "plain"))
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(msg.as_string())
```

### 4.7 JPEG (Charts/Visualizations)

**Pattern**: Generate charts using `matplotlib` (if available) or `PIL` for simple graphics.

```python
# If matplotlib is available:
import matplotlib.pyplot as plt

def write_chart_jpeg(output_path: Path, data: dict, title: str):
    """Write bar chart to JPEG."""
    fig, ax = plt.subplots()
    ax.bar(data.keys(), data.values())
    ax.set_title(title)
    ax.set_ylabel("Value")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, format="jpeg", dpi=100, bbox_inches="tight")
    plt.close()

# If only PIL is available:
from PIL import Image, ImageDraw

def write_simple_jpeg(output_path: Path, width: int, height: int, text: str):
    """Write simple image with text."""
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), text, fill="black")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="JPEG")
```

## 5. Routing & Constraints

### 5.1 One-Output-Per-Message

**Pattern**: Generate one output file for each input message.

```python
def one_output_per_message(messages: list, output_dir: Path, format_func):
    """Generate one output file per message."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for msg in messages:
        output_path = output_dir / f"{msg['id']}.txt"
        format_func(output_path, msg)
```

### 5.2 One-Output-Per-Recipient

**Pattern**: Group messages by recipient, generate one output per recipient.

```python
def one_output_per_recipient(messages: list, output_dir: Path, format_func):
    """Generate one output file per recipient."""
    from collections import defaultdict
    
    by_recipient = defaultdict(list)
    for msg in messages:
        by_recipient[msg["recipient"]].append(msg)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    for recipient, msgs in by_recipient.items():
        output_path = output_dir / f"{recipient}.txt"
        format_func(output_path, msgs)
```

### 5.3 Deduplication

**Pattern**: Remove duplicate source rows before processing.

```python
def deduplicate_rows(rows: list, key_fields: list):
    """Remove duplicate rows based on key fields."""
    seen = set()
    unique = []
    
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    
    return unique
```

## 6. Preservation & Consistency

### 6.1 Preserve Original Content

**Invariant**: When modifying existing artifacts (e.g., adding events to a calendar), preserve all original content.

```python
def add_events_to_calendar(existing_ics: Path, new_events: list, output_ics: Path):
    """Add events to existing calendar while preserving original events."""
    # Parse existing calendar
    with open(existing_ics, "rb") as f:
        cal = Calendar.from_ical(f.read())
    
    # Add new events
    for event_data in new_events:
        event = Event()
        event.add("summary", event_data["summary"])
        event.add("dtstart", event_data["start"])
        event.add("dtend", event_data["end"])
        cal.add_component(event)
    
    # Write to output (original events preserved)
    with open(output_ics, "wb") as f:
        f.write(cal.to_ical())
```

### 6.2 Cross-Output Fact Consistency

**Invariant**: When generating multiple outputs from the same source (e.g., TXT summary + ICS calendar), ensure facts agree across outputs.

```python
def generate_consistent_outputs(events: list, txt_path: Path, ics_path: Path):
    """Generate TXT and ICS outputs with consistent facts."""
    # Use same data source for both outputs
    # TXT summary
    blocks = []
    for event in events:
        block = f"Event: {event['summary']}\nDate: {event['start']}"
        blocks.append(block)
    write_txt(txt_path, blocks)
    
    # ICS calendar (same events, same facts)
    write_ics(ics_path, events)
```

**Key principle**: Extract facts once, pass to all output generators. Never re-parse or re-extract for each output.

## 7. Testing Pattern

**Pattern**: Structure `solve.py` with a `run()` function that tests can import and call.

```python
# solve.py
from pathlib import Path

_BASE = Path(__file__).resolve().parent

def run():
    # All workflow logic here
    input_path = _BASE / "data" / "input"
    output_path = _BASE / "data" / "output"
    # ... processing ...

if __name__ == "__main__":
    run()
```

**Test invocation**:
```python
# test_solve.py
from solve import run

def test_workflow():
    run()
    # Verify outputs
    assert (_BASE / "data" / "output").exists()
```

## 8. Common Pitfalls

1. **Path fragility**: Always use `Path(__file__).resolve().parent` as base, not relative paths from CWD.
2. **Email header encoding**: Use `policy.default` to auto-decode RFC 2047 headers. With `compat32`, you get raw encoded strings.
3. **Multipart body extraction**: Use `msg.walk()` + check `get_content_type() == "text/plain"`. Don't assume single-part structure.
4. **Datetime types in iCalendar**: `dtstart.dt` can be `date` or `datetime`. Check type before operations.
5. **JSON serialization**: Use `default=str` in `json.dump()` to handle datetime objects.
6. **File endings**: TXT files should end with exactly one newline. Use `"\n\n".join(blocks) + "\n"`.
7. **PDF text extraction quality**: `pypdf.extract_text()` varies by PDF generation. For tables, consider `pdfplumber` if available.
8. **Excel formulas vs values**: Use `data_only=True` in `openpyxl.load_workbook()` to get calculated values.
9. **Manual data inspection (calibrated)**: Default to writing code from the task spec without inspecting source files — the parsers handle structural edge cases. However, inspect one sample file when: (a) your code fails or produces unexpected output, (b) the task requires understanding content format not in the spec (e.g., "extract dates" without specifying format, "extract table from PDF" where layout varies), or (c) you need to discover schema (e.g., XLSX column names). One targeted inspection saves many debugging iterations when the task underdetermines content format.
10. **Excessive verification**: After running your solution, pick ONE verification method and trust it. Do NOT chain multiple checks (cat → xxd → python byte check). If `cat output.txt` shows correct content, you're done. If you need to check exact bytes, use `python3 -c "data=open('file').read(); print(repr(data[-10:]))"` — but don't also run xxd, od, or cat -A. One method, one check.

## 9. Library Availability

**Verified available** (as of v01 environment):
- `icalendar` 5.0.13
- `pypdf` 5.1.0
- `openpyxl` 3.1.5
- `python-docx` (import as `docx`) 1.1.2
- `PIL` (Pillow) 11.1.0
- `reportlab` 4.2.5

**Not available** (use alternatives):
- `pdfplumber` → use `pypdf`
- `PyPDF2` → use `pypdf`
- `pandas` → use `openpyxl` directly
- `matplotlib` → use `PIL` for simple graphics
- `bs4` → use `html.parser` from stdlib

When writing solutions, check library availability and fall back to alternatives as needed.
