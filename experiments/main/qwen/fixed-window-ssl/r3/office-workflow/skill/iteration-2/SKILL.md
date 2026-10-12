---
name: office-workflow
description: >
  General method for office-workflow tasks that read source office artifacts
  (MIME email, iCalendar, PDF, XLSX), apply selection/filtering criteria,
  extract relevant content, and produce destination artifacts (TXT, ICS,
  JPEG, DOCX, EML, PDF, JSON, or in-place calendar updates) while respecting
  ordering, routing, and cross-output consistency constraints.
---

# Office Workflow Skill

## Overview

Office-workflow tasks share a common pipeline structure:

```
DISCOVER sources → PARSE each source → SELECT/ FILTER → EXTRACT content → FORMAT output → WRITE destination(s)
```

The specific artifact types, selection criteria, extraction targets, and output formats vary across the family, but the pipeline shape and the key decisions at each stage are invariant.

## Tooling Boundaries

**Critical**: The task environment (`/app`) is isolated from the host workspace. Use the correct tools:
- **Host workspace tools** (`read`, `write`, `edit`, `ls`, `find`, `grep`): Operate on the skill package and task definition files in the host workspace. Cannot access `/app`.
- **`task_shell`**: Executes commands inside the `/app` container. Use this for all task execution: writing `solve.py`, running Python, exploring `/app/data`, verifying outputs.

**Pattern**: Use `task_shell` with heredoc to write files inside `/app`:
```bash
cat > /app/solve.py << 'PYEOF'
import os
# ... solution code ...
PYEOF
```

Then execute and verify:
```bash
cd /app && python3 solve.py && cat data/answer.txt
```

Do NOT attempt `ls /app` or `read /app/...` with host tools — they will fail with WORKSPACE_BOUNDARY errors.

## Step 1: Discover Source Artifacts

Identify all source files from the task description. Common patterns:
- **Directory scan**: `os.listdir(dir)` filtered by extension (`.eml`, `.ics`, `.pdf`, `.xlsx`)
- **Explicit file list**: Task names specific files
- **Glob patterns**: Use `glob.glob()` for pattern-based discovery

Always verify the directory exists and handle the case of zero matching files gracefully.

## Step 2: Parse Source Artifacts (Format-Specific)

Each source format requires its own parser. Use the correct library and API:

### MIME Email (.eml)
```python
import email
from email import policy

with open(filepath, 'rb') as f:
    msg = email.message_from_bytes(f.read(), policy=policy.default)
```
- Use `policy.default` (Python 3.6+) for modern API access
- Access headers: `msg['subject']`, `msg['from']`, `msg['to']`, `msg['date']`
- **Multipart messages**: These are `multipart/mixed` or `multipart/alternative`. Do NOT call `get_payload()` on the top-level message expecting a string. Instead:
  ```python
  body_part = msg.get_body(preferencelist=('plain',))
  body_text = body_part.get_content().strip()
  ```
- Legacy alternative: iterate `msg.walk()`, find `part.get_content_type() == 'text/plain'`, then `part.get_payload(decode=True).decode(charset)`
- For HTML bodies: `msg.get_body(preferencelist=('html',))` — may need HTML-to-text conversion

### iCalendar (.ics)
```python
import icalendar

with open(filepath, 'rb') as f:
    cal = icalendar.Calendar.from_ical(f.read())

for component in cal.walk():
    if component.name == 'VEVENT':
        summary = component.get('summary')
        dtstart = component.get('dtstart').dt
        dtend = component.get('dtend').dt
        # ... other properties
```

### XLSX Tables
```python
import openpyxl

wb = openpyxl.load_workbook(filepath, data_only=True)
ws = wb.active  # or wb[sheet_name]
for row in ws.iter_rows(values_only=True):
    # process row tuple
```

### PDF
- For reading: `PyPDF2` or `pdfplumber` if available; otherwise use `reportlab` for generation only
- For generation: `reportlab` (confirmed available in standard environments)

### DOCX
```python
import docx

doc = docx.Document(filepath)
for para in doc.paragraphs:
    text = para.text
# For tables:
for table in doc.tables:
    for row in table.rows:
        for cell in row.cells:
            text = cell.text
```

## Step 3: Select / Filter

Apply the task's selection criteria. Common patterns:
- **Exact header match**: `subject in target_set` — use a set for O(1) lookup
- **Pattern match**: regex on subject/body/from/to
- **Date-based filtering**: parse dates, compare against ranges
- **Recipient-based routing**: filter by To/Cc/Bcc headers
- **Content-based**: keyword search in body text
- **Row-level filtering** (XLSX): predicate on cell values

**Critical**: The filter criteria come from the task instruction. Read them precisely — "exactly 'scheduled meeting'" means exact string equality, not substring match.

## Step 4: Extract Content

After selection, extract the specific content the task requires:
- **Email body**: plain-text content, stripped of leading/trailing whitespace
- **Calendar fields**: summary, dates, location, attendees, description
- **Table data**: specific columns, aggregated values, filtered rows
- **PDF text**: page content, specific sections

**"Stripped" body** means applying `.strip()` to remove leading/trailing whitespace (including newlines). Content inside the body (like "Sent at:" lines) is part of the body and must be preserved.

## Step 5: Format and Write Output

### TXT Output
Common format patterns:
```
Subject: <header value>
<body content>

Subject: <header value>
<body content>
```
- Blocks separated by exactly one blank line (`\n\n`)
- File ends with exactly one newline
- No header/footer beyond what the task specifies

### ICS Output
```python
cal = icalendar.Calendar()
cal.add('prodid', '-//Workflow//')
cal.add('version', '2.0')
event = icalendar.Event()
event.add('summary', summary)
event.add('dtstart', start_datetime)
event.add('dtend', end_datetime)
cal.add_component(event)
with open(output_path, 'wb') as f:
    f.write(cal.to_ical())
```

### JSON Output
```python
import json
with open(output_path, 'w') as f:
    json.dump(data, f, indent=2)
```

### DOCX Output
```python
doc = docx.Document()
doc.add_heading('Title', level=1)
doc.add_paragraph('Body text')
doc.save(output_path)
```

### EML Output
Construct a MIME message and serialize:
```python
from email.mime.text import MIMEText
msg = MIMEText(body_text)
msg['Subject'] = subject
msg['From'] = from_addr
msg['To'] = to_addr
with open(output_path, 'wb') as f:
    f.write(msg.as_bytes())
```

## Step 6: Ordering and Routing

### Ordering
- **By filename**: `selected.sort(key=lambda x: x[0])` — alphabetical sort on the source filename
- **By date**: sort by parsed datetime objects
- **By subject**: sort by subject string
- Task instruction specifies the ordering; follow it exactly

### Routing
- **One output per message**: Each selected source produces one output block/file
- **One output per recipient**: Group by recipient, produce separate outputs
- **Single consolidated output**: All selected items in one file
- **In-place update**: Modify an existing calendar/document

## Step 7: Preservation and Consistency

### What Must Be Preserved
- Original source files are never modified (unless task says "in-place update")
- Original calendar events remain when adding new ones
- Selected email bodies are reproduced faithfully (only stripped of outer whitespace)

### Cross-Output Consistency
When the same data appears in multiple outputs:
- Dates must be identical across TXT and ICS representations
- Quantitative summaries must match between machine-readable (JSON) and visual (JPEG) outputs
- Recipient-specific facts must be consistent across paired outputs (e.g., PDF + email to same person)
- Extracted dates/facts must be the same wherever referenced

## Implementation Pattern

**All parameters below (marked `# FROM TASK`) must be extracted from the task instruction, not hardcoded from examples.**

```python
import os
# Import format-specific parsers based on source_artifacts (FROM TASK)
import email
from email import policy

def run():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. DISCOVER: source directory and file pattern (FROM TASK)
    # Example: "Read every .eml file in data/emails/Bob/"
    source_dir = os.path.join(base_dir, 'data', 'emails', 'Bob')  # FROM TASK
    file_extension = '.eml'  # FROM TASK
    
    # 2. SELECT: filter criteria (FROM TASK)
    # Example: "Select only messages whose Subject is exactly 'scheduled meeting' or 'application approved'"
    target_subjects = {'scheduled meeting', 'application approved'}  # FROM TASK
    
    # 3. PARSE and FILTER
    selected = []
    for fname in os.listdir(source_dir):
        if not fname.endswith(file_extension):
            continue
        fpath = os.path.join(source_dir, fname)
        
        # Format-specific parsing (see Step 2 above)
        with open(fpath, 'rb') as f:
            msg = email.message_from_bytes(f.read(), policy=policy.default)
        
        # Apply filter criteria
        subject = msg['subject']
        if subject not in target_subjects:
            continue
        
        # 4. EXTRACT: content target (FROM TASK)
        # Example: "the complete, stripped plain-text body"
        body_part = msg.get_body(preferencelist=('plain',))
        if body_part is None:
            continue
        body_text = body_part.get_content().strip()
        
        selected.append((fname, subject, body_text))
    
    # 5. ORDER: sorting criterion (FROM TASK)
    # Example: "Sort the selected messages by source filename"
    selected.sort(key=lambda x: x[0])  # FROM TASK
    
    # 6. FORMAT: output structure (FROM TASK)
    # Example: "For each selected message, write one block containing:
    #           Subject: <the complete Subject header>
    #           <the complete, stripped plain-text body>
    #           Separate adjacent blocks with one blank line"
    blocks = []
    for fname, subject, body in selected:
        blocks.append(f"Subject: {subject}\n{body}")  # FROM TASK
    
    output = '\n\n'.join(blocks) + '\n'  # FROM TASK (separator and ending)
    
    # 7. WRITE: output path (FROM TASK)
    # Example: "write data/answer.txt"
    output_path = os.path.join(base_dir, 'data', 'answer.txt')  # FROM TASK
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(output)
```

## Scheduling Variants (Interval Intersection)

When the task requires finding common free-time windows across multiple calendars, the algorithm is a three-phase interval computation:

### Phase 1: Extract and Normalize Busy Intervals

```python
import icalendar
from datetime import datetime, date, timezone

def normalize_dt(d):
    """Convert date or tz-aware datetime to naive datetime (UTC)."""
    if hasattr(d, 'hour'):  # datetime (possibly tz-aware)
        if d.tzinfo is not None:
            d = d.astimezone(timezone.utc).replace(tzinfo=None)
        return d
    else:  # date object (all-day event)
        return datetime(d.year, d.month, d.day)

def extract_busy(cal_path):
    """Extract sorted busy intervals from an .ics file."""
    with open(cal_path, 'rb') as f:
        cal = icalendar.Calendar.from_ical(f.read())
    busy = []
    for comp in cal.walk():
        if comp.name == 'VEVENT':
            start = normalize_dt(comp.get('dtstart').dt)
            end = normalize_dt(comp.get('dtend').dt)
            busy.append((start, end))
    busy.sort()
    return busy
```

**Critical type pitfalls**:
- `icalendar` returns `datetime.date` for all-day events and `datetime.datetime` for timed events
- `date` and `datetime` cannot be compared directly → `TypeError`
- Timezone-aware and naive `datetime` cannot be compared → `TypeError`
- Always normalize all datetimes to naive UTC before any interval arithmetic

### Phase 2: Merge Busy Intervals

```python
def merge_intervals(intervals):
    """Merge overlapping/touching intervals. Input: sorted list of (start, end)."""
    if not intervals:
        return []
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(m) for m in merged]
```

### Phase 3: Compute Free Complement and Intersect

```python
def free_intervals(busy_merged, window_start, window_end):
    """Free intervals = complement of busy within [window_start, window_end]."""
    free = []
    current = window_start
    for start, end in busy_merged:
        if start > current:
            free.append((current, start))
        current = max(current, end)
    if current < window_end:
        free.append((current, window_end))
    return free

def intersect_intervals(a, b):
    """Intersect two sorted lists of non-overlapping intervals."""
    result = []
    i, j = 0, 0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if start < end:
            result.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return result

def find_common_free(calendars, window_start, window_end, min_duration=None):
    """Find common free windows across all calendars."""
    # Start with full window as "free"
    common_free = [(window_start, window_end)]
    
    for cal_path in calendars:
        busy = merge_intervals(extract_busy(cal_path))
        person_free = free_intervals(busy, window_start, window_end)
        common_free = intersect_intervals(common_free, person_free)
    
    if min_duration:
        common_free = [(s, e) for s, e in common_free
                       if (e - s).total_seconds() >= min_duration]
    
    return common_free
```

### Scheduling Edge Cases
- **Empty calendar** → entire window is free
- **Fully booked calendar** → no free intervals
- **Overlapping events** → merge_intervals handles this
- **Events outside window** → clipped by free_intervals computation
- **All-day events** → normalized to midnight datetime, treated as busy for full day

## Cross-Source Consistency

When the same fact appears in multiple source artifacts (e.g., a meeting date in both an email and a calendar), the task may require:

### Verification (facts must agree)
```python
def verify_consistency(fact_sources):
    """Check that all sources report the same value for a fact."""
    values = set()
    for source_name, value in fact_sources:
        values.add(value)
    if len(values) > 1:
        raise ValueError(f"Inconsistent values: {fact_sources}")
    return values.pop()
```

### Conflict Resolution (pick authoritative source)
When sources disagree and the task specifies a resolution order:
- Calendar overrides email (calendar is the system of record for schedules)
- Most recent timestamp wins
- Explicit task instruction overrides defaults

### Consistency Checks in Outputs
When producing multiple outputs from the same data:
- **TXT + ICS**: The date/time in the text summary must match the DTSTART/DTEND in the calendar
- **JSON + JPEG**: Quantitative values in the data must match labels/values in the chart
- **PDF + Email**: Individualized facts (name, amount, date) must be identical in both
- **Multiple recipients**: Each person's output contains only their own data, but shared facts (meeting time, location) must be consistent across all

### Implementation Pattern
```python
# Extract fact from multiple sources
email_date = parse_date_from_email(email_msg)
cal_date = parse_date_from_calendar(cal_event)

# Verify or reconcile
if email_date != cal_date:
    # Use task-specified resolution: e.g., calendar wins
    final_date = cal_date
else:
    final_date = email_date

# Use final_date consistently in ALL outputs
write_txt_report(final_date, ...)
write_ics_event(final_date, ...)
```

## Key Pitfalls and Checks

1. **MIME multipart handling**: Never assume `get_payload()` returns a string on the top-level message. Always use `get_body()` or `walk()`.
2. **Subject comparison**: Use exact string equality unless the task says "contains" or "matches pattern". Header values from `msg['subject']` are strings.
3. **Body stripping**: `.strip()` removes leading/trailing whitespace including `\n`, `\r`, spaces. Internal whitespace (blank lines within the body) is preserved.
4. **Path anchoring**: Use `os.path.dirname(os.path.abspath(__file__))` as base for relative paths, since tests may `chdir` before calling `run()`.
5. **File ending**: TXT files should end with exactly one `\n`. Use `'\n\n'.join(blocks) + '\n'` pattern.
6. **Encoding**: Always read `.eml` files in binary mode (`'rb'`) and parse with `email.message_from_bytes`. Write text outputs in text mode with default UTF-8 encoding.
7. **Empty results**: If no messages match, write an empty file (just a newline or truly empty, depending on task spec).
8. **Date/datetime type mixing**: `icalendar` returns `datetime.date` for all-day events and `datetime.datetime` for timed events. These cannot be compared. Always normalize with a helper that converts `date` → `datetime(year, month, day)`.
9. **Timezone-aware vs naive**: `icalendar` may return tz-aware datetimes. Comparing aware and naive datetimes raises `TypeError`. Normalize all to naive UTC before interval arithmetic.
10. **Interval merge correctness**: When merging busy intervals, use `<=` (not `<`) for the overlap check so that touching intervals (end of one = start of next) are merged.

## Available Libraries (Standard Environment)

| Library | Use For |
|---------|---------|
| `email` (stdlib) | MIME email parsing and construction |
| `icalendar` | iCalendar (.ics) parsing and generation |
| `openpyxl` | XLSX reading and writing |
| `docx` | DOCX reading and writing |
| `PIL` (Pillow) | Image processing, JPEG output |
| `reportlab` | PDF generation |
| `json` (stdlib) | JSON output |
| `csv` (stdlib) | CSV parsing |

## Adapting to New Variants

When facing a new office-workflow task:
1. **Identify source format(s)** from file extensions and task description
2. **Identify selection criteria** — what makes a source item "selected"?
3. **Identify extraction targets** — what content from each selected item?
4. **Identify output format(s)** and structure
5. **Identify ordering** — how should outputs be arranged?
6. **Identify routing** — one output, per-recipient, per-message?
7. **Identify consistency requirements** — what facts must agree across outputs?
8. **Map to the pipeline**: DISCOVER → PARSE → SELECT → EXTRACT → FORMAT → WRITE
9. **Choose the right parser** from the library table above
10. **Verify output format** matches spec exactly (separators, endings, encoding)
