---
name: office-workflow
description: >
  Reusable skill for office-automation workflow tasks that parse source artifacts
  (MIME email, iCalendar, PDF, XLSX), apply filtering/routing/transformation logic,
  and produce destination artifacts (TXT, ICS, JPEG, DOCX, EML, PDF, JSON).
  Covers MIME-aware email parsing, calendar manipulation, spreadsheet extraction,
  document generation, and multi-artifact reconciliation with preservation constraints.
---

# Office Workflow Skill

## Core Pattern

Office-workflow tasks follow a consistent structure:

1. **Parse** source artifacts (emails, calendars, spreadsheets, PDFs)
2. **Filter/Transform** based on content criteria (subjects, dates, recipients, values)
3. **Format** results into destination artifact(s)
4. **Preserve** source content and maintain cross-output consistency

**First step**: Read the task instruction carefully to identify all four components.

## Decision Framework

Identify the workflow relation from the task instruction to choose the right approach:

| Workflow Relation | Source → Destination | Key Technique |
|-------------------|---------------------|---------------|
| **Relevance filtering** | Emails/docs → TXT/JSON | Parse + filter by criteria + format |
| **Conflict-free scheduling** | Calendars → ICS | Find free time windows, avoid overlaps |
| **Fact/table extraction** | PDF/XLSX → TXT/JSON | Extract structured data, preserve formatting |
| **Quantitative analysis + visualization** | XLSX → JPEG/chart | Compute stats, generate plots |
| **Summarization + scheduling** | Emails → TXT + ICS | Extract key info, create calendar events |
| **Notification** | Events → Emails | Generate personalized messages |
| **Recipient-based routing + format conversion** | Mixed → per-recipient outputs | Group by recipient, convert formats |

## Critical Implementation Details

### MIME Email Parsing (Most Common)

**Always use `policy.default`** for clean header decoding:

```python
from email import policy
from email.parser import BytesParser

with open(filepath, "rb") as f:
    msg = BytesParser(policy=policy.default).parse(f)

subject = msg["Subject"]  # Returns str, RFC 2047 decoded automatically
```

Without `policy.default`, headers return as `Header` objects or encoded bytes.

**Body extraction** from multipart messages:

```python
body_part = msg.get_body(preferencelist=("plain",))
body = body_part.get_content().strip() if body_part else ""
```

Use `get_body()` — don't iterate parts manually. It correctly handles `multipart/alternative`, `multipart/mixed`, and nested structures.

### Subject Matching

- **Exact and case-sensitive** unless task says otherwise
- `"scholarship approved"` ≠ `"application approved"`
- **Filename ≠ Subject**: Always parse the header, never infer from filename

### Output Formatting

Build the full string in memory, then write once:

```python
blocks = []
for item in selected:
    blocks.append(f"Subject: {subject}\n{body}")

output = "\n\n".join(blocks) + "\n"  # Blank line separator, single trailing newline
```

**Note**: When bodies contain internal blank lines, you cannot unambiguously split on `\n\n`. Evaluators use exact string comparison or parse by `Subject:` line starts.

## Source Artifact Parsing

### MIME Email (.eml)

See "MIME Email Parsing" above.

### iCalendar (.ics)

**Reading:**
```python
from icalendar import Calendar

with open(filepath, "rb") as f:
    cal = Calendar.from_ical(f.read())

events = []
for component in cal.walk():
    if component.name == "VEVENT":
        events.append({
            "summary": str(component.get("SUMMARY", "")),
            "dtstart": component.get("DTSTART").dt,
            "dtend": component.get("DTEND").dt,
            "location": str(component.get("LOCATION", ""))
        })
```

**Writing:**
```python
from icalendar import Calendar, Event
from datetime import datetime

cal = Calendar()
cal.add("prodid", "-//My Product//EN")
cal.add("version", "2.0")

event = Event()
event.add("summary", "Meeting")
event.add("dtstart", datetime(2024, 3, 23, 10, 0))
event.add("dtend", datetime(2024, 3, 23, 11, 0))
cal.add_component(event)

with open("output.ics", "wb") as f:
    f.write(cal.to_ical())
```

### XLSX Spreadsheets

```python
import openpyxl

wb = openpyxl.load_workbook(filepath, data_only=True)
ws = wb.active  # or wb["SheetName"]

# Read all rows
for row in ws.iter_rows(min_row=1, values_only=True):
    # row is a tuple of cell values
    pass

# Read specific range
for row in ws["A1:D10"]:
    for cell in row:
        print(cell.value)
```

### PDF

```python
import pdfplumber

with pdfplumber.open(filepath) as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        tables = page.extract_tables()  # list of 2D lists
```

## Destination Artifact Writing

### Plain Text (TXT)

```python
with open("output.txt", "w") as f:
    f.write(output)
```

### JSON

```python
import json

with open("output.json", "w") as f:
    json.dump(data, f, indent=2)
```

### DOCX

```python
from docx import Document

doc = Document()
doc.add_heading("Title", level=1)
doc.add_paragraph("Body text")
doc.save("output.docx")
```

### Email (EML)

```python
from email.message import EmailMessage
from email import policy

msg = EmailMessage()
msg["Subject"] = "Subject"
msg["From"] = "sender@example.com"
msg["To"] = "recipient@example.com"
msg.set_content("Body")

with open("output.eml", "wb") as f:
    f.write(msg.as_bytes(policy=policy.default))
```

### Image (JPEG/PNG) — for quantitative analysis + visualization

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.bar(categories, values)
ax.set_title("Analysis Results")
plt.savefig("output.jpeg", dpi=150, bbox_inches='tight')
plt.close()
```

## Advanced Workflow Patterns

### Conflict-Free Scheduling

Find common free time across multiple calendars:

```python
from datetime import datetime, timedelta

def find_free_slots(calendars, duration_minutes=60):
    """Find time slots when all calendars are free."""
    # Collect all busy times
    busy_times = []
    for cal_events in calendars:
        for event in cal_events:
            busy_times.append((event["dtstart"], event["dtend"]))
    
    # Sort by start time
    busy_times.sort()
    
    # Find gaps
    free_slots = []
    # ... merge overlapping busy times, find gaps >= duration
    return free_slots
```

### Quantitative Analysis + Visualization

Extract data from XLSX, compute stats, generate chart:

```python
import openpyxl
import matplotlib.pyplot as plt
from collections import defaultdict

# Extract data
wb = openpyxl.load_workbook("data.xlsx", data_only=True)
ws = wb.active

data = defaultdict(list)
for row in ws.iter_rows(min_row=2, values_only=True):
    category, value = row[0], row[1]
    data[category].append(value)

# Compute statistics
stats = {cat: sum(vals)/len(vals) for cat, vals in data.items()}

# Generate visualization
fig, ax = plt.subplots()
ax.bar(stats.keys(), stats.values())
ax.set_ylabel("Average Value")
plt.savefig("analysis.jpeg", dpi=150)
```

### Recipient-Based Routing + Format Conversion

Group messages by recipient, generate individualized outputs:

```python
from collections import defaultdict

by_recipient = defaultdict(list)
for msg in all_messages:
    by_recipient[msg["To"]].append(msg)

for recipient, messages in by_recipient.items():
    # Generate personalized output for this recipient
    output = generate_personalized_output(recipient, messages)
    
    # Write in required format
    if format == "txt":
        write_txt(f"output_{recipient}.txt", output)
    elif format == "pdf":
        write_pdf(f"output_{recipient}.pdf", output)
```

### Multi-Artifact Reconciliation

When the same fact must appear in multiple outputs (e.g., date in TXT and ICS):

```python
# Extract once
meeting_info = extract_meeting_info(email)

# Use in multiple outputs
write_txt_summary(meeting_info)  # Uses meeting_info["date"]
write_ics_event(meeting_info)    # Uses same meeting_info["date"]

# This ensures consistency across outputs
```

## Verification Pattern

After writing output, verify with Python (not shell tools like `xxd` which may not be available):

```python
with open("data/answer.txt", "r") as f:
    content = f.read()

# Check format
assert content.endswith("\n"), "Must end with newline"
assert not content.endswith("\n\n"), "Must not end with double newline"

# For exact verification, compare against expected string
expected = "Subject: ...\n...\n\nSubject: ...\n...\n"
assert content == expected, f"Mismatch"
```

**Stop when verified**: Once output matches expected format, the task is complete. Do not perform redundant verification steps (e.g., cat solve.py, echo "verified", re-run unnecessarily).

## Critical Pitfalls

1. **MIME headers without policy**: Always use `policy=policy.default` with `BytesParser`
2. **Subject matching**: Exact and case-sensitive; filename ≠ Subject header
3. **Multipart body extraction**: Use `get_body(preferencelist=("plain",))`, not manual iteration
4. **File path boundaries**: Write outputs relative to `/app/` using `task_shell`, not workspace `write` tool
5. **Output formatting**: Build full string in memory, write once; pay attention to separators and trailing newlines
6. **Sorting**: Sort by `os.path.basename(filepath)`, not full path
7. **Stripping whitespace**: "Stripped body" means `.strip()` on extracted text
8. **Output verification**: Use Python for verification, not shell tools; bodies with internal blank lines make naive splitting ambiguous
9. **Redundant verification**: Don't waste tool calls on unnecessary checks after output is verified

## Implementation Checklist

- [ ] Read task instruction to identify: source types, filter criteria, output format, preservation constraints
- [ ] Identify workflow relation from decision framework
- [ ] Choose correct parser for each source type
- [ ] Use `policy=policy.default` for all email parsing
- [ ] Extract bodies with `get_body(preferencelist=("plain",))`
- [ ] Apply filter criteria exactly as specified (case-sensitive unless told otherwise)
- [ ] Sort/organize results per task requirements
- [ ] Format output exactly as specified (separators, headers, trailing newline)
- [ ] Write output to correct path relative to `/app/`
- [ ] Verify output with Python (exact string comparison when possible)
- [ ] **Stop when verified** — don't perform redundant checks

## Family Variation Dimensions

The office-workflow family varies along these axes:

| Dimension | What Changes | Examples |
|-----------|-------------|----------|
| **workflow_relation** | Semantic operation | Relevance filtering, scheduling, extraction, analysis + visualization, summarization, notification, routing + format conversion |
| **source_artifacts** | Input types | MIME email (.eml), iCalendar (.ics), PDF, XLSX, or combinations |
| **destination_artifacts** | Output formats | TXT, ICS, JPEG, DOCX, EML, PDF, JSON, in-place calendar updates |
| **temporal_and_routing_constraints** | Where/when rules | Recipient identity, subject relevance, class membership, duplicate rows, free-time windows, one-output-per-message vs per-recipient |
| **preservation_and_consistency** | What must remain intact | Original events, selected bodies, extracted dates, shared summaries, recipient folders, individualized facts across paired outputs |

Identify which values each dimension takes, then apply appropriate techniques.

## Reference Implementation

See `scripts/email_filter_to_txt.py` for a complete v01-style implementation demonstrating the core pattern.
