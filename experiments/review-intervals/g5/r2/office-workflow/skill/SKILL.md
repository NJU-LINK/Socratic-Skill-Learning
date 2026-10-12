---
name: office-workflow
description: >
  General pipeline for office-automation workflows that read heterogeneous
  source artifacts (EML, ICS, PDF, XLSX), apply selection/filtering criteria,
  extract or transform content, and write destination artifacts (TXT, ICS,
  JSON, DOCX, PDF, EML, JPEG) with correct routing and cross-output
  consistency.
---

# Office Workflow Skill

This skill covers a family of office-automation tasks that share a common
pipeline structure. Each task instructs an agent to read one or more source
artifacts, apply domain-specific selection or transformation logic, and
produce one or more destination artifacts. The spec axes that vary across
family members are:

| Axis | What varies |
|------|-------------|
| **workflow_relation** | Relevance filtering, scheduling, extraction, quantitative analysis, summarization, notification, routing |
| **source_artifacts** | MIME email (.eml), iCalendar (.ics), PDF, XLSX, or combinations |
| **destination_artifacts** | TXT, ICS, JPEG, DOCX, EML, PDF, structured JSON, in-place calendar updates |
| **temporal_and_routing_constraints** | Subject match, recipient identity, date windows, free-time intersections, deduplication, per-recipient routing |
| **preservation_and_consistency** | Existing content that must remain intact; facts shared across multiple outputs |

## Pipeline (applies to every family member)

### 1. Discovery — enumerate source artifacts

Determine the source directory/file pattern from the task instruction. Use
`glob` or `os.listdir` to collect file paths.

```python
import glob, os
eml_files = sorted(glob.glob(os.path.join("data", "emails", "Bob", "*.eml")))
```

**Key decisions:**
- Always sort file paths for deterministic output ordering unless the task
  specifies a different sort key.
- The source directory and file extension come from the instruction — do not
  hardcode v01 values.

### 2. Parsing — use the correct parser for each artifact type

| Artifact | Library | Entry point |
|----------|---------|-------------|
| `.eml` (MIME email) | `email` (stdlib) | `email.message_from_binary_file(f, policy=email.policy.default)` |
| `.ics` (iCalendar) | `icalendar` | `icalendar.Calendar.from_ical(data)` |
| `.pdf` | `pypdf` | `pypdf.PdfReader(path)` → `reader.pages[i].extract_text()` |
| `.xlsx` | `openpyxl` | `openpyxl.load_workbook(path)` |
| `.docx` (read) | `python-docx` | `docx.Document(path)` |

**EML parsing detail (multipart MIME):**
Use a two-pass approach to handle nested multipart structures correctly:

1. **First pass:** find any `multipart/alternative` container and extract its
   `text/plain` child. This is the actual body in most modern emails.
2. **Fallback:** if no `multipart/alternative` exists, use the first
   `text/plain` part encountered.

This avoids grabbing boilerplate disclaimers like "This message contains
HTML. Please view in an HTML-capable client." that some mail clients place
at the outer level before the real `multipart/alternative` body.

```python
import email, email.policy

with open(fpath, "rb") as f:
    msg = email.message_from_binary_file(f, policy=email.policy.default)

# Fallback: first text/plain at any level
fallback_body = None
for part in msg.walk():
    if part.get_content_type() == "text/plain":
        fallback_body = part.get_content()  # returns str with policy=default
        break

# Preferred: text/plain inside multipart/alternative
alt_body = None
for part in msg.walk():
    if part.get_content_type() == "multipart/alternative":
        for subpart in part.walk():
            if subpart.get_content_type() == "text/plain":
                alt_body = subpart.get_content()
                break
        break

body = alt_body if alt_body is not None else fallback_body
```

**Header access:** Use `msg.get("Subject", "")` — returns the decoded header
value as a string when using `email.policy.default`.

**PDF text extraction:**
```python
from pypdf import PdfReader
reader = PdfReader(path)
full_text = "\n".join(page.extract_text() for page in reader.pages)
```

**XLSX cell iteration:**
```python
from openpyxl import load_workbook
wb = load_workbook(path, data_only=True)
ws = wb.active
for row in ws.iter_rows(values_only=True):
    # row is a tuple of cell values
```

### 3. Selection / filtering — apply the criterion from the instruction

The filtering criterion varies per task. Common patterns:

- **Exact subject match:** `subject in {"scheduled meeting", "application approved"}`
- **Keyword/substring match:** `"approved" in subject.lower()`
- **Date range:** compare parsed dates against bounds
- **Recipient-based:** match `To`/`Cc` headers against a name list
- **Content-based:** search body text for keywords
- **Row-level (XLSX):** filter rows by column value, class membership, or
  duplicate detection

### 4. Extraction / transformation — pull relevant content

What to extract depends on the workflow relation:

- **Relevance filtering:** the full body text of matching messages
- **Fact extraction:** specific data points (dates, amounts, names)
- **Quantitative analysis:** compute sums, averages, counts from table data
- **Summarization:** condense content into shorter form
- **Scheduling:** extract date/time from messages and create calendar events

**Body text handling — `rstrip("\n")` vs `strip()`:**
Use `body.rstrip("\n")` rather than `body.strip()`. The `rstrip("\n")` call
removes only trailing newlines (which are artifacts of MIME encoding) while
preserving any intentional leading whitespace or indentation. A future
variant might have an indented body where `strip()` would destroy formatting.
If the task requires exact body reproduction, `rstrip("\n")` is the safer
default.

### 5. Assembly — construct destination artifacts

| Destination | Library / method |
|-------------|-----------------|
| `.txt` | Plain string formatting, write with `open(path, "w")` |
| `.ics` | `icalendar.Event()` → add to `Calendar` → serialize |
| `.json` | `json.dumps(data, indent=2)` |
| `.docx` | `docx.Document()` → `add_paragraph()`, `add_table()` |
| `.pdf` | `reportlab.pdfgen.canvas` |
| `.eml` | `email.message.EmailMessage()` → serialize |
| `.jpeg` | `PIL.Image` (no matplotlib available) |
| In-place ICS update | Parse existing ICS, add/modify events, re-serialize |

**TXT block format (common pattern):**
```
Subject: <subject>
<body text>

Subject: <subject>
<body text>
```
Separate blocks with one blank line. End the file with exactly one newline.

```python
blocks = []
for fname, subject, body in selected:
    blocks.append(f"Subject: {subject}\n{body}")
output = "\n\n".join(blocks) + "\n"
```

**ICS event creation:**
```python
from icalendar import Calendar, Event
from datetime import datetime

cal = Calendar()
event = Event()
event.add("summary", "Meeting")
event.add("dtstart", datetime(2024, 3, 23, 14, 0))
event.add("dtend", datetime(2024, 3, 23, 15, 0))
cal.add_component(event)
with open("output.ics", "wb") as f:
    f.write(cal.to_ical())
```

### 6. Routing / output — write to correct location

- **Single output file:** write to the path specified in the instruction.
- **Per-recipient routing:** create separate files/folders per recipient.
- **Per-message output:** one output file per selected source message.
- **In-place update:** read existing file, modify, write back.

Always use `os.makedirs(os.path.dirname(path), exist_ok=True)` before writing.

### 7. Consistency check — verify cross-output agreement

When the task produces multiple outputs that share facts (e.g., a number in
both a JSON summary and a chart, or a date in both a TXT file and an ICS
event):

- Extract shared facts once into variables.
- Use the same variables in all outputs.
- If modifying existing content (e.g., adding events to a calendar), verify
  that original events remain intact.

## Available libraries (confirmed in environment)

| Purpose | Library | Import |
|---------|---------|--------|
| Email parsing | stdlib `email` | `import email, email.policy` |
| Calendar (ICS) | `icalendar` 5.x | `from icalendar import Calendar, Event` |
| PDF reading | `pypdf` 5.x | `from pypdf import PdfReader` |
| PDF generation | `reportlab` 4.x | `from reportlab.pdfgen import canvas` |
| XLSX | `openpyxl` 3.x | `from openpyxl import load_workbook` |
| DOCX | `python-docx` 1.x | `from docx import Document` |
| Images | `Pillow` 11.x | `from PIL import Image, ImageDraw` |

**Not available:** `pdfplumber`, `pandas`, `matplotlib`. For tabular analysis
use `openpyxl` cell iteration or the `csv` module. For charts, draw manually
with Pillow or skip if not required.

## Worked example: v01 email filtering

**Task:** Read `.eml` files from `data/emails/Bob/`, select messages with
Subject exactly `"scheduled meeting"` or `"application approved"`, sort by
filename, write `data/answer.txt` with blocks of `Subject: <subject>\n<body>`
separated by blank lines, ending with one newline.

```python
import email, email.policy, os, glob

def run():
    # [GENERAL] Discovery stage — change glob pattern for different artifact types
    # e.g., "data/invoices/*.pdf" for PDF, "data/roster/*.xlsx" for XLSX
    email_dir = os.path.join("data", "emails", "Bob")
    output_path = os.path.join("data", "answer.txt")
    
    # [v01-SPECIFIC] These subjects come from the instruction.
    # Other variants may filter by date range, recipient, keyword, or column value.
    target_subjects = {"scheduled meeting", "application approved"}

    eml_files = sorted(glob.glob(os.path.join(email_dir, "*.eml")))
    selected = []

    for fpath in eml_files:
        # [GENERAL] Parsing stage — use correct parser for artifact type
        # For PDF: PdfReader(path); for XLSX: load_workbook(path)
        with open(fpath, "rb") as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
        
        # [GENERAL] Selection stage — apply criterion from instruction
        subject = msg.get("Subject", "")
        if subject in target_subjects:
            # [GENERAL] Extraction stage — two-pass body extraction handles
            # both simple and nested MIME structures
            fallback_body = None
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    fallback_body = part.get_content()
                    break

            alt_body = None
            for part in msg.walk():
                if part.get_content_type() == "multipart/alternative":
                    for subpart in part.walk():
                        if subpart.get_content_type() == "text/plain":
                            alt_body = subpart.get_content()
                            break
                    break

            body = alt_body if alt_body is not None else fallback_body
            # [GENERAL] rstrip("\n") is the safe default for all variants
            body = body.rstrip("\n") if body else ""
            selected.append((os.path.basename(fpath), subject, body))

    # [GENERAL] Sort by filename ensures deterministic output order
    selected.sort(key=lambda x: x[0])
    
    # [GENERAL] Assembly stage — construct destination artifacts
    # For ICS: create Event objects; for JSON: json.dumps(); for DOCX: add_paragraph()
    blocks = [f"Subject: {subj}\n{body}" for _, subj, body in selected]
    output = "\n\n".join(blocks) + "\n"

    # [GENERAL] Routing/output stage — write to correct location
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(output)
```

**Why this works:**
- `email.policy.default` gives decoded string headers and `get_content()`
  that returns `str` for text parts.
- Two-pass body extraction prefers `text/plain` inside `multipart/alternative`
  (the real body) over boilerplate at the outer level.
- `rstrip("\n")` removes trailing MIME newlines without destroying leading
  whitespace.
- Sorting by basename ensures deterministic output order.
- `"\n\n".join(blocks) + "\n"` produces blocks separated by one blank line,
  ending with exactly one newline.

### Adapting this example to other variants

The v01 example demonstrates the full pipeline. To adapt it for other family
members, change the parts marked `[v01-SPECIFIC]` and adjust the parser/assembly
for the artifact types:

| Instruction phrase | Code change |
|-------------------|-------------|
| "Read every `.pdf` in `data/invoices/`" | Change glob to `data/invoices/*.pdf`, parser to `PdfReader` |
| "Select rows where column A > 100" | Replace subject filter with row-level condition on XLSX data |
| "Write one `.ics` file per recipient" | Add per-recipient routing in Assembly stage, use `icalendar.Event` |
| "Extract dates from message bodies" | Add regex/dateutil parsing in Extraction stage |
| "Summarize each message in 2 sentences" | Add summarization logic (e.g., first 2 sentences) in Extraction |
| "Update existing calendar with new events" | Read existing ICS, add events, re-serialize (preservation axis) |

## Common pitfalls (failure modes across variants)

These are expert-known failure modes that cause silent incorrectness. Check
for them when working with each artifact type.

### PDF: empty text from scanned documents
`pypdf.PdfReader.pages[i].extract_text()` silently returns `""` for scanned
PDFs that have no extractable text layer. Always verify extraction returned
non-empty content:

```python
text = "\n".join(p.extract_text() for p in reader.pages)
if not text.strip():
    # Scanned PDF — no text layer. OCR may be needed (pytesseract if available).
    raise ValueError("PDF contains no extractable text (possibly scanned)")
```

### XLSX: merged cells return None
`openpyxl` returns `None` for all cells in a merged range except the top-left
cell. When iterating rows, detect merges and propagate the top-left value:

```python
# Build a merge map: (row, col) -> value of top-left cell
merge_map = {}
for merge_range in ws.merged_cells.ranges:
    top_left_value = ws.cell(merge_range.min_row, merge_range.min_col).value
    for row in range(merge_range.min_row, merge_range.max_row + 1):
        for col in range(merge_range.min_col, merge_range.max_col + 1):
            merge_map[(row, col)] = top_left_value

# When reading a cell:
def get_cell(ws, row, col):
    val = ws.cell(row, col).value
    if val is None and (row, col) in merge_map:
        return merge_map[(row, col)]
    return val
```

### ICS: timezone-aware vs naive datetime comparison
`icalendar` returns timezone-aware datetime objects. Comparing them with
naive datetimes raises `TypeError`. Always normalize before comparison:

```python
from datetime import timezone

def normalize_dt(dt):
    """Strip timezone info after converting to UTC, for safe comparison."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
```

### Email: header folding under compat32 policy
Long Subject headers can be folded across multiple lines in raw MIME (with
`\n\t` continuations). `email.policy.default` handles unfolding automatically,
but if code ever uses `compat32` policy, the raw folded string is returned.
Always prefer `email.policy.default` (or `email.policy.strict`) to avoid this.

### Email: nested multipart with boilerplate text/plain
Some mail clients (especially Outlook/Exchange) place a boilerplate
text/plain part at the outer level before the real body inside
`multipart/alternative`:

```
multipart/mixed
├── text/plain ("This message contains HTML. View in HTML client.")  ← boilerplate
├── multipart/alternative
│   ├── text/html (the real body)
│   └── text/plain (the real body)  ← what we want
└── image/png
```

A simple walk-and-break on first `text/plain` grabs the boilerplate instead
of the real body. The fix is the two-pass approach documented in the Parsing
section: prefer `text/plain` inside `multipart/alternative`, fall back to
first `text/plain` otherwise.

## Generalization checklist for new variants

When facing a new family member, walk through:

1. **What are the source artifacts?** → Choose the right parser.
2. **What is the selection criterion?** → Implement the filter.
3. **What content needs extraction?** → Body text, table rows, dates, etc.
4. **What is the destination format?** → Choose the right writer.
5. **Is there routing logic?** → Per-recipient, per-message, or single output.
6. **Are there consistency constraints?** → Shared facts across outputs.
7. **Must existing content be preserved?** → Read-modify-write carefully.
