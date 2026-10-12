---
name: office-workflow
description: >
  Generalized methodology for office-workflow tasks: parsing heterogeneous
  office artifacts (MIME email, iCalendar, PDF, XLSX), applying filtering and
  routing logic based on spec-declared constraints, generating structured
  outputs (TXT, ICS, DOCX, PDF, JSON, EML), and ensuring cross-output
  consistency and source preservation.
---

# Office Workflow Skill

## Overview

This skill covers a family of tasks where an agent must:
1. Read one or more office artifacts (emails, calendars, spreadsheets, PDFs)
2. Apply domain-specific filtering, extraction, or transformation logic
3. Write one or more output artifacts in a specified format
4. Preserve source content and maintain factual consistency across outputs

The spec defines five variation axes:
- **workflow_relation**: what semantic operation connects source to destination
- **source_artifacts**: which office formats are inputs
- **destination_artifacts**: which formats are outputs
- **temporal_and_routing_constraints**: rules governing where/when outputs go
- **preservation_and_consistency**: what must remain unchanged and what must agree

## Quick Start: Email Filtering Template

For simple email-filtering tasks (the most common case), use this complete skeleton. Fill in the bracketed placeholders from the task instruction, then run and verify.

```python
import os
import email
from email import policy


def run():
    # === CONFIGURATION (fill in from task instruction) ===
    BASE = os.path.dirname(os.path.abspath(__file__))
    EMAIL_DIR = os.path.join(BASE, "data", "emails", "[RECIPIENT]")  # e.g., "Bob"
    OUTPUT_PATH = os.path.join(BASE, "data", "[OUTPUT_FILE]")  # e.g., "answer.txt"
    
    # Filter criteria
    TARGET_SUBJECTS = {"[SUBJECT_1]", "[SUBJECT_2]"}  # exact match
    
    # === IMPLEMENTATION ===
    # 1. Collect and sort source files
    files = sorted(f for f in os.listdir(EMAIL_DIR) if f.endswith(".eml"))
    
    # 2. Parse and filter
    selected = []
    for fname in files:
        filepath = os.path.join(EMAIL_DIR, fname)
        with open(filepath, "rb") as fh:
            msg = email.message_from_binary_file(fh, policy=policy.default)
        
        subject = str(msg["Subject"])  # coerce for RFC 2047 safety
        if subject in TARGET_SUBJECTS:
            # Extract plain-text body
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset).strip()
                    break
            selected.append((fname, subject, body))
    
    # 3. Generate output
    blocks = [f"Subject: {subject}\n{body}" for _, subject, body in selected]
    output = "\n\n".join(blocks) + "\n"
    
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        f.write(output)


if __name__ == "__main__":
    run()
```

**When to use this template:**
- Task reads `.eml` files from a directory
- Filters by exact subject match
- Writes structured text output
- Sorts by filename

**When to use the full framework instead:**
- Multiple source artifact types (email + calendar + spreadsheet)
- Complex routing (per-recipient outputs)
- Scheduling or calendar manipulation
- In-place updates to existing files
- Cross-artifact reconciliation

## Efficiency Tips

**Skip manual exploration when the task instruction is complete.** If the instruction specifies:
- Exact source directory and file pattern
- Exact filter criteria (subject match, recipient, date range)
- Exact output format and location

Then you can write code directly from the instruction without reading individual source files. The task instruction contains all necessary information.

**Verify once, not three times.** After writing code:
1. Run it: `python3 -c "from solve import run; run()"`
2. Check output format: `cat data/answer.txt` or verify with a single Python assertion
3. Done. Don't re-run or re-verify unless something fails.

**Batch file operations.** When you need to inspect multiple source files, use a single loop or shell command instead of reading each file individually.

## Workflow Decision Framework

**Note:** For simple email-filtering tasks, use the Quick Start Template above. This framework is for complex variants with multiple artifact types, routing logic, scheduling, or in-place updates.

When encountering a new variant, follow this structured analysis before coding:

### Step 1: Parse the Task Instruction

Extract these key elements from the task instruction:

1. **Source artifacts**: What files/formats must be read? (e.g., "every `.eml` file in `data/emails/Bob/`")
2. **Filtering/routing logic**: What determines which artifacts are selected or how they're routed? (e.g., "Subject is exactly `scheduled meeting` or `application approved`")
3. **Output format**: What artifact(s) must be written? (e.g., "write `data/answer.txt`" with specific format)
4. **Preservation requirements**: What must remain unchanged? (e.g., "Do not include any header or body text from other messages")
5. **Sorting/ordering**: How should outputs be ordered? (e.g., "Sort the selected messages by source filename")

### Step 2: Map to Spec Axes

Determine which spec axes are instantiated:

**workflow_relation** — What semantic operation connects source to destination?
- **Relevance filtering**: Select artifacts matching criteria (v01 case)
- **Conflict-free scheduling**: Find common free-time windows across calendars
- **Fact/table extraction**: Extract specific data from tables or documents
- **Quantitative analysis**: Compute statistics and generate visualizations
- **Summarization + scheduling**: Summarize content and create calendar events
- **Notification**: Generate notifications based on triggers
- **Recipient-based routing**: Route outputs to specific recipients based on content

**source_artifacts** — What formats are inputs?
- Single format: all emails, all calendars, all spreadsheets
- Mixed formats: emails + calendars, spreadsheets + PDFs
- Combinations requiring reconciliation: merge data from multiple sources

**destination_artifacts** — What formats are outputs?
- Single output: one TXT file, one ICS file, one JSON file
- Multiple outputs: one per recipient, one per message, one per category
- In-place updates: modify existing calendar or document

**temporal_and_routing_constraints** — What rules govern where/when outputs go?
- Subject-based relevance: filter by subject line
- Recipient identity: route by To/From/Cc fields
- Date-range filtering: select by temporal criteria
- Class membership: group by category or type
- Duplicate detection: handle repeated entries
- Free-time windows: find common availability
- One-output-per-message: generate one output per source artifact
- One-output-per-recipient: generate personalized outputs

**preservation_and_consistency** — What must remain intact?
- Source immutability: never modify input files
- Cross-output consistency: same facts must agree across all outputs
- Individualized facts: recipient-specific data must be accurate in each output

### Step 3: Select Implementation Strategy

Based on the axes identified:

1. **Choose parser(s)** for source artifact types (see Section 2 below)
2. **Implement filtering/routing logic** per the constraint axis
3. **Generate output(s)** in the specified destination format (see Section 5 below)
4. **Verify preservation invariants** (see Section 6 below)

### Example: v01 Analysis

Task: "Read every `.eml` file in `data/emails/Bob/`... Select only messages whose Subject is exactly `scheduled meeting` or `application approved`... Sort by source filename and write `data/answer.txt`"

- **workflow_relation**: Relevance filtering (select by subject)
- **source_artifacts**: MIME email (.eml), single directory
- **destination_artifacts**: TXT file, single output
- **temporal_and_routing_constraints**: Subject-based relevance (exact match)
- **preservation_and_consistency**: Source immutability, exclude non-matching messages

Implementation: Parse emails → filter by subject → sort by filename → write TXT

## Core Procedure

### 1. Environment and Path Resolution

Tests typically call `from solve import run; run()`. The working directory at
test time may differ from the source directory. Always anchor paths to
`__file__`:

```python
import os
BASE = os.path.dirname(os.path.abspath(__file__))
input_path = os.path.join(BASE, "data", ...)
output_path = os.path.join(BASE, "data", ...)
```

Use `os.makedirs(..., exist_ok=True)` for output directories.

### 2. Parsing Office Artifacts

#### MIME Email (.eml)
Use Python's `email` module with `policy.default`:

```python
import email
from email import policy

with open(filepath, "rb") as fh:
    msg = email.message_from_binary_file(fh, policy=policy.default)

# Headers — always coerce to str to handle RFC 2047 encoded subjects
subject = str(msg["Subject"])  # exact string comparison
from_addr = str(msg["From"])
to_addr = str(msg["To"])

# Body extraction — walk MIME parts
for part in msg.walk():
    if part.get_content_type() == "text/plain":
        payload = part.get_payload(decode=True)
        charset = part.get_content_charset() or "utf-8"
        body_text = payload.decode(charset)
```

Key points:
- Always open in `"rb"` mode and use `message_from_binary_file`
- Use `.get_payload(decode=True)` to handle transfer encodings
- Default charset to `"utf-8"` if `get_content_charset()` returns None
- `msg.walk()` handles multipart/mixed, multipart/alternative, etc.
- **Always coerce headers with `str()`** — with `policy.default`, non-ASCII
  subjects (RFC 2047 encoded like `=?utf-8?b?...?=`) return an
  `email.header.Header` object, not a `str`. Comparing a `Header` with `==`
  against a plain string silently fails. `str(msg["Subject"])` forces the
  decoded string representation.

#### iCalendar (.ics)
Use `icalendar` library (`pip install icalendar`) or parse manually.
Extract VEVENT components:

```python
from icalendar import Calendar
with open(filepath, "rb") as fh:
    cal = Calendar.from_ical(fh.read())
for event in cal.walk("VEVENT"):
    summary = event.get("SUMMARY")
    dtstart = event.get("DTSTART").dt
    dtend = event.get("DTEND").dt
```

#### XLSX Spreadsheets
Use `openpyxl` (`pip install openpyxl`):

```python
import openpyxl
wb = openpyxl.load_workbook(filepath)
ws = wb.active
for row in ws.iter_rows(values_only=True):
    # process row tuple
```

#### PDF
Use `pdfplumber` (`pip install pdfplumber`) or `PyPDF2` for text extraction:

```python
import pdfplumber
with pdfplumber.open(filepath) as pdf:
    for page in pdf.pages:
        text = page.extract_text()
```

### 3. Filtering and Selection Logic

The spec's `temporal_and_routing_constraints` axis determines selection rules.
Common patterns:

- **Exact subject match**: `if subject in {"scheduled meeting", "application approved"}`
- **Recipient-based routing**: `if "Bob" in msg["To"]`
- **Date-range filtering**: `if start_date <= event_date <= end_date`
- **Keyword relevance**: `if keyword.lower() in body.lower()`
- **Duplicate detection**: track seen keys in a set

Always determine whether matching is exact or partial, case-sensitive or not.
The task instruction is the authority.

### 4. Sorting

When the task says "sort by source filename", use `sorted()` on filenames:

```python
files = sorted(f for f in os.listdir(dir) if f.endswith(".eml"))
```

For date-based sorting, parse dates into comparable datetime objects first.

### 5. Output Generation

#### TXT Output
Standard pattern for block-structured text:

```python
blocks = []
for item in selected_items:
    blocks.append(f"Subject: {item.subject}\n{item.body.strip()}")
output = "\n\n".join(blocks) + "\n"
with open(output_path, "w") as f:
    f.write(output)
```

Key formatting rules:
- "stripped" body means `.strip()` applied
- Blocks separated by one blank line (`\n\n`)
- File ends with exactly one trailing newline
- No extra headers or footers unless specified

#### ICS Output
```python
from icalendar import Calendar, Event
from datetime import datetime

cal = Calendar()
cal.add("prodid", "-//My Workflow//EN")
cal.add("version", "2.0")

for item in items:
    event = Event()
    event.add("summary", item.summary)
    event.add("dtstart", item.start)
    event.add("dtend", item.end)
    cal.add_component(event)

with open(output_path, "wb") as f:
    f.write(cal.to_ical())
```

#### JSON Output
```python
import json
data = [{"subject": s, "body": b} for s, b in selected]
with open(output_path, "w") as f:
    json.dump(data, f, indent=2)
```

### 6. Preservation and Consistency

- **Never modify source files** unless the task explicitly says to update in-place
- **Cross-output consistency**: if the same fact appears in multiple outputs
  (e.g., a date in both a TXT summary and an ICS calendar), ensure they match
  exactly — use the same parsed value, not re-formatted independently
- **Recipient-based individualization**: when generating per-recipient outputs,
  each recipient's file must contain only their relevant data

### 7. Testing and Verification

After writing `solve.py`:

```bash
# Test direct execution
python3 solve.py

# Test import-based invocation (as tests will call it)
python3 -c "from solve import run; run()"

# Verify output format
python3 -c "
with open('data/answer.txt', 'rb') as f:
    content = f.read()
print(repr(content))
# Check trailing newline
assert content.endswith(b'\n')
assert not content.endswith(b'\n\n')
"
```

## Common Pitfalls

1. **Path resolution**: Using relative paths like `"data/answer.txt"` instead of
   anchoring to `__file__`. Tests may run from a different CWD.

2. **MIME body extraction**: Trying to parse MIME boundaries manually instead of
   using `msg.walk()`. The `email` module handles this reliably.

3. **Charset handling**: Assuming ASCII or not handling None charset. Always
   default to `"utf-8"`.

4. **Subject comparison**: Using `in` for substring matching when exact match is
   required, or applying case-folding when not specified. Also: forgetting to
   coerce `msg["Subject"]` to `str()` — RFC 2047 encoded headers return a
   `Header` object that won't `==` a plain string.

5. **Output formatting**: Forgetting `.strip()` on body text, or adding extra
   newlines at the end. The pattern `"\n\n".join(blocks) + "\n"` is reliable.

6. **Sorting**: Forgetting to sort when specified, or sorting by wrong key
   (e.g., by date when filename is required).

## Dependency Management

The email-parsing code above uses only the Python standard library (`email`,
`os`). Other artifact parsers are third-party:

| Library | Install | Used for |
|---------|---------|----------|
| `icalendar` | `pip install icalendar` | .ics parsing/writing |
| `openpyxl` | `pip install openpyxl` | .xlsx reading/writing |
| `pdfplumber` | `pip install pdfplumber` | PDF text extraction |
| `PyPDF2` | `pip install PyPDF2` | Alternative PDF extraction |
| `python-docx` | `pip install python-docx` | .docx generation |

When a variant requires one of these, verify availability at the top of
`solve.py` with a clear error:

```python
try:
    import openpyxl
except ImportError:
    raise SystemExit("openpyxl is required for XLSX parsing. Install with: pip install openpyxl")
```

Or install proactively in the solution script:

```python
import subprocess, sys
subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
```

## Generalization Strategy

When encountering a new variant:

1. **Apply the Workflow Decision Framework** (above) to analyze the task instruction
2. **Map to spec axes** to understand the variant's requirements
3. **Ensure required third-party libraries are installed** (see Dependency Management)
4. **Select the appropriate parser(s)** for the source artifact type(s)
5. **Implement the filtering/routing logic** per the constraint axis
6. **Generate output(s)** in the specified destination format(s)
7. **Verify preservation invariants** (source unchanged, cross-output consistency)
8. **Test both direct execution and import-based invocation**

### Handling Complex Variants

**Multiple source artifact types**: When the task requires reading emails + calendars + spreadsheets:
- Parse each artifact type using the appropriate parser
- Reconcile data across sources (e.g., match email dates with calendar events)
- Ensure cross-source consistency in outputs

**Recipient-based routing**: When outputs must be routed to specific recipients:
- Group source artifacts by recipient (To/From/Cc fields)
- Generate one output per recipient with only their relevant data
- Ensure individualized facts are accurate in each output

**In-place updates**: When the task requires modifying existing files:
- Load the existing file (e.g., calendar)
- Apply changes (add/remove/modify events)
- Preserve all existing content not explicitly modified
- Write back to the same file path

**Cross-output consistency**: When the same fact appears in multiple outputs:
- Parse the fact once and store in a variable
- Use the same variable in all outputs
- Never re-format or re-parse independently for each output
