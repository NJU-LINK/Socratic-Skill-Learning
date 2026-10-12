---
name: office-workflow
description: >
  General methodology for office-workflow tasks that read one or more source
  office artifacts (MIME email, iCalendar, PDF, XLSX), apply a semantic
  workflow relation (filtering, scheduling, extraction, analysis,
  summarization, notification, routing), and materialize destination artifacts
  (TXT, ICS, JPEG, DOCX, EML, PDF, JSON, or in-place calendar updates) while
  respecting temporal/routing constraints and preserving source content
  consistency.
---

# Office Workflow Skill

## Quick Start: 3-Step Process for Any Task

**When you encounter a new office-workflow task, follow these 3 steps:**

1. **Decompose**: Extract the 5 dimensions (sources, relation, destinations, constraints, preservation) using the table in §1
2. **Navigate**: Use the Quick-Reference table in §1 to find the relevant parsing, workflow, and output sections
3. **Implement**: Write robust code with error handling (see §5.6 for edge cases) and multi-source reconciliation if needed (see §6)

**Critical reminder**: Always use `Path(__file__).resolve().parent` for path resolution, define a `run()` function, handle edge cases gracefully, and ensure cross-output consistency when generating multiple outputs.

## 1. Task Decomposition Protocol

Every office-workflow task follows the same abstract structure:

```
SOURCE ARTIFACTS  →  WORKFLOW LOGIC  →  DESTINATION ARTIFACTS
                      ↑
              CONSTRAINTS & PRESERVATION
```

**Before writing any code, extract these five dimensions from the task instruction:**

| Dimension | What to identify | Questions to ask |
|-----------|-----------------|------------------|
| **Source artifacts** | File types, locations, structure | What files am I reading? Where are they? What format? |
| **Workflow relation** | Transformation connecting source→destination | Am I filtering, scheduling, extracting, analyzing, summarizing, notifying, or routing? |
| **Destination artifacts** | Output file types, locations, format | What am I creating? Where does it go? What format? |
| **Temporal/routing constraints** | Filtering criteria, sort order, recipient rules | What determines which outputs go where/when? |
| **Preservation requirements** | What must remain unchanged, what must be consistent | What source content must be preserved exactly? What facts must agree across outputs? |

**Example decomposition (v01):**
- Sources: `.eml` files in `data/emails/Bob/`
- Relation: Relevance filtering (select by Subject)
- Destinations: `data/answer.txt` with formatted blocks
- Constraints: Subject ∈ {"scheduled meeting", "application approved"}, sort by filename
- Preservation: Complete body text including "Sent at:" lines

### Quick-Reference: Task → Section Mapping

When you encounter a new variant task, use this table to find the relevant sections quickly:

| Task says... | Go to Section |
|---|---|
| `.eml` files, filter by subject/from | §2.1 + §3.1 + §4.1 |
| `.ics` files, find free time | §2.2 + §3.2 + §4.2 |
| `.pdf` files, extract tables | §2.3 + §3.3 + §4.3/§4.6 |
| `.xlsx` files, analyze/visualize | §2.4 + §3.4 + §4.5/§4.7 |
| Multiple source types | §2 (all relevant) + §6.1 + §6.2 |
| Route outputs to recipients | §3.7 + §4 (per format) |
| Generate notifications | §3.6 + §4.1 |
| Summarize and schedule | §3.5 + §4.2 |
| Multiple outputs (TXT + ICS + JSON) | §6.3 + §4 (all relevant) |
| Reconcile conflicting data | §6.2 + §6.4 |

## 2. Parsing Recipes by Source Type

### 2.1 MIME Email (.eml)

**Library:** Python's built-in `email` module

**Correct pattern:**
```python
from email import policy
from email.parser import BytesParser

with open(eml_path, "rb") as f:
    msg = BytesParser(policy=policy.default).parse(f)

# Headers
subject = msg["Subject"]  # returns str with policy.default
from_addr = msg["From"]
to_addr = msg["To"]

# Body extraction — walk MIME tree for text/plain
body_part = msg.get_body(preferencelist=("plain",))
body_text = body_part.get_content()  # auto-decodes charset
```

**Critical gotchas:**
- Always open in binary mode (`"rb"`) and use `BytesParser`
- `policy.default` gives modern string handling (no legacy MIME header encoding)
- `get_body(preferencelist=("plain",))` finds the first text/plain part in multipart messages
- `.get_content()` handles charset decoding automatically
- **Embedded metadata is body content**: Lines like "Sent at: 2024-03-23 10:00:00" that appear inside the MIME text/plain part ARE part of the body — do not strip them

### 2.2 iCalendar (.ics)

**Library:** `icalendar`

**Reading:**
```python
from icalendar import Calendar

with open(ics_path, "rb") as f:
    cal = Calendar.from_ical(f.read())

events = []
for component in cal.walk():
    if component.name == "VEVENT":
        events.append({
            "summary": str(component.get("SUMMARY")),
            "dtstart": component.get("DTSTART").dt,
            "dtend": component.get("DTEND").dt,
            "uid": str(component.get("UID"))
        })
```

**Updating (preserving existing events):**
```python
# Read existing calendar
with open(ics_path, "rb") as f:
    cal = Calendar.from_ical(f.read())

# Add new event
new_event = Event()
new_event.add("summary", "New Meeting")
new_event.add("dtstart", datetime(2024, 3, 24, 10, 0, 0))
new_event.add("dtend", datetime(2024, 3, 24, 11, 0, 0))
cal.add_component(new_event)

# Write back
with open(ics_path, "wb") as f:
    f.write(cal.to_ical())
```

**Gotcha:** When updating, always read the existing calendar first and add to it — never overwrite blind.

### 2.3 PDF

**Library:** `pymupdf` (fitz) or `pdfplumber`

**Text extraction:**
```python
import fitz  # pymupdf

doc = fitz.open(pdf_path)
full_text = ""
for page in doc:
    full_text += page.get_text()
doc.close()
```

**Table extraction (pdfplumber):**
```python
import pdfplumber

with pdfplumber.open(pdf_path) as pdf:
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                # process row
                pass
```

**Gotcha:** Multi-page documents need page iteration. Tables may span pages — check for continuation.

### 2.4 XLSX (Spreadsheets)

**Library:** `openpyxl` for reading/writing, `pandas` for analysis

**Reading:**
```python
import openpyxl

wb = openpyxl.load_workbook(xlsx_path)
ws = wb.active

# Iterate rows
for row in ws.iter_rows(values_only=True):
    # row is a tuple of cell values
    pass

# Or access specific cells
value = ws["A1"].value
```

**Writing:**
```python
import openpyxl

wb = openpyxl.Workbook()
ws = wb.active
ws["A1"] = "Header"
ws.append(["Row 1", "Data"])
wb.save(output_path)
```

**Gotcha:** Handle duplicate rows explicitly if the task mentions them. Preserve formatting if required.

## 3. Workflow Patterns

### 3.1 Relevance Filtering

**Pattern:** Select artifacts matching criteria (subject, content, metadata)

```python
TARGET_SUBJECTS = {"scheduled meeting", "application approved"}
selected = []
for eml_path in sorted(data_dir.glob("*.eml")):
    with open(eml_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    if msg["Subject"] in TARGET_SUBJECTS:
        selected.append(msg)
```

**Variants:**
- Filter by header fields (Subject, From, To, Date)
- Filter by body content (regex, keyword matching)
- Filter by metadata (file size, creation date)

### 3.2 Conflict-Free Scheduling

**Pattern:** Find time slots that don't overlap across multiple calendars

```python
from datetime import datetime, timedelta

# Collect all busy intervals
busy_intervals = []
for ics_file in calendar_files:
    events = parse_calendar(ics_file)
    for event in events:
        busy_intervals.append((event["dtstart"], event["dtend"]))

# Sort by start time
busy_intervals.sort()

# Merge overlapping intervals
merged = []
for start, end in busy_intervals:
    if merged and start <= merged[-1][1]:
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    else:
        merged.append((start, end))

# Find free slots (e.g., between 9 AM and 5 PM)
work_start = datetime(2024, 3, 24, 9, 0, 0)
work_end = datetime(2024, 3, 24, 17, 0, 0)

free_slots = []
current = work_start
for busy_start, busy_end in merged:
    if current < busy_start:
        free_slots.append((current, busy_start))
    current = max(current, busy_end)
if current < work_end:
    free_slots.append((current, work_end))
```

### 3.3 Fact or Table Extraction

**Pattern:** Extract structured data from unstructured sources

```python
import re

# Extract dates
dates = re.findall(r'\d{4}-\d{2}-\d{2}', text)

# Extract currency amounts
amounts = re.findall(r'\$[\d,]+\.?\d*', text)

# Extract email addresses
emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', text)

# Extract tables from PDF
import pdfplumber
with pdfplumber.open(pdf_path) as pdf:
    tables = []
    for page in pdf.pages:
        for table in page.extract_tables():
            tables.append(table)
```

### 3.4 Quantitative Analysis and Visualization

**Pattern:** Compute statistics, generate visualizations

```python
import pandas as pd
import matplotlib.pyplot as plt

# Read data
df = pd.read_excel(xlsx_path)

# Compute statistics
summary = df.groupby('category').agg({
    'value': ['mean', 'sum', 'count', 'std']
})

# Generate visualization
fig, ax = plt.subplots(figsize=(10, 6))
summary['value']['mean'].plot(kind='bar', ax=ax)
ax.set_ylabel('Average Value')
ax.set_title('Analysis by Category')
plt.tight_layout()
fig.savefig(output_path, dpi=150)
plt.close()
```

### 3.5 Summarization Plus Scheduling

**Pattern:** Combine text summarization with calendar operations

```python
# Extract key information from email
def extract_meeting_info(email_body):
    import re
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', email_body)
    times = re.findall(r'\d{1,2}:\d{2}', email_body)
    subjects = re.findall(r'(?:meeting|call|discussion)\s+(?:about|on|for)\s+(.+?)(?:\.|$)', 
                         email_body, re.IGNORECASE)
    return {
        "dates": dates,
        "times": times,
        "subject": subjects[0] if subjects else "Meeting"
    }

# Create calendar event from extracted info
info = extract_meeting_info(email_body)
event = Event()
event.add("summary", info["subject"])
event.add("dtstart", parse_datetime(info["dates"][0], info["times"][0]))
event.add("dtend", parse_datetime(info["dates"][0], info["times"][0]) + timedelta(hours=1))
```

### 3.6 Notification

**Pattern:** Generate alerts from events

```python
from datetime import datetime, timedelta

# Check for upcoming events
def check_upcoming_events(calendar_path, hours_ahead=24):
    events = parse_calendar(calendar_path)
    now = datetime.now()
    threshold = now + timedelta(hours=hours_ahead)
    
    upcoming = []
    for event in events:
        if now <= event["dtstart"] <= threshold:
            upcoming.append(event)
    
    return upcoming

# Generate notification
upcoming = check_upcoming_events("calendar.ics")
if upcoming:
    notification = "REMINDER: You have {} upcoming event(s):\n".format(len(upcoming))
    for event in upcoming:
        notification += f"- {event['summary']} at {event['dtstart']}\n"
    
    with open("notification.txt", "w") as f:
        f.write(notification)
```

### 3.7 Recipient-Based Routing and Format Conversion

**Pattern:** Generate outputs per recipient with individualized content

```python
from collections import defaultdict
from pathlib import Path

# Group messages by recipient
recipient_messages = defaultdict(list)
for eml_path in data_dir.glob("*.eml"):
    with open(eml_path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    recipient = msg["To"]
    recipient_messages[recipient].append(msg)

# Generate one output per recipient
for recipient, messages in recipient_messages.items():
    # Create recipient-specific folder
    recipient_folder = output_dir / recipient.split("@")[0]
    recipient_folder.mkdir(parents=True, exist_ok=True)
    
    # Generate personalized summary
    summary = generate_summary(messages)
    
    # Write in requested format (e.g., PDF)
    output_path = recipient_folder / "summary.pdf"
    write_pdf(output_path, summary)
    
    # Also send as email
    eml_path = recipient_folder / "summary.eml"
    write_email(eml_path, recipient, summary)
```

## 4. Output Format Recipes

### 4.1 TXT Output

**Format:** Blocks separated by one blank line, file ends with one newline

```python
blocks = []
for item in selected_items:
    block = f"Subject: {item['subject']}\n{item['body']}"
    blocks.append(block)

# Join with blank line separator, add trailing newline
output_text = "\n\n".join(blocks) + "\n"

with open(output_path, "w", encoding="utf-8") as f:
    f.write(output_text)
```

**Critical:** 
- Separator between blocks is `\n\n` (one blank line)
- File ends with exactly one `\n`
- No leading blank line
- Body content is preserved exactly (including embedded "Sent at:" lines)

### 4.2 ICS Output (iCalendar)

```python
from icalendar import Calendar, Event
from datetime import datetime

cal = Calendar()
cal.add("prodid", "-//Office Workflow//EN")
cal.add("version", "2.0")

for event_data in events:
    event = Event()
    event.add("summary", event_data["summary"])
    event.add("dtstart", event_data["dtstart"])
    event.add("dtend", event_data["dtend"])
    event.add("uid", event_data.get("uid", f"{datetime.now().timestamp()}@workflow"))
    cal.add_component(event)

with open(ics_path, "wb") as f:
    f.write(cal.to_ical())
```

### 4.3 DOCX Output

```python
from docx import Document

doc = Document()
doc.add_heading("Summary", 0)

for item in items:
    doc.add_heading(item["title"], level=1)
    doc.add_paragraph(item["content"])

doc.save(docx_path)
```

### 4.4 EML Output (Email)

```python
from email.message import EmailMessage
from email import policy

msg = EmailMessage()
msg["Subject"] = "Forwarded: Meeting Summary"
msg["From"] = "workflow@example.com"
msg["To"] = "recipient@example.com"
msg.set_content(body_text)

with open(eml_path, "wb") as f:
    f.write(bytes(msg))
```

### 4.5 PDF Output

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas(pdf_path, pagesize=letter)
width, height = letter

y = height - 72
c.setFont("Helvetica-Bold", 16)
c.drawString(72, y, "Summary Report")
y -= 30

c.setFont("Helvetica", 12)
for item in items:
    c.drawString(72, y, item["title"])
    y -= 20
    c.drawString(72, y, item["content"])
    y -= 30
    
    if y < 72:  # New page if needed
        c.showPage()
        y = height - 72

c.save()
```

### 4.6 JSON Output

```python
import json

output_data = {
    "items": [
        {
            "subject": item["subject"],
            "body": item["body"],
            "metadata": item.get("metadata", {})
        }
        for item in selected_items
    ]
}

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(output_data, f, indent=2, ensure_ascii=False)
```

### 4.7 JPEG Output (Visualization)

```python
import matplotlib.pyplot as plt
import numpy as np

fig, ax = plt.subplots(figsize=(10, 6))

# Generate plot
x = np.arange(len(data))
ax.bar(x, data)
ax.set_xticks(x)
ax.set_xticklabels(labels, rotation=45)
ax.set_ylabel("Value")
ax.set_title("Analysis")

plt.tight_layout()
fig.savefig(jpeg_path, format="jpeg", dpi=150)
plt.close()
```

## 5. Cross-Cutting Concerns

### 5.1 Path Resolution

**Always anchor paths to the script location, not the current working directory:**

```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent  # Directory containing solve.py
data_dir = BASE_DIR / "data" / "emails" / "Bob"
output_path = BASE_DIR / "data" / "answer.txt"
```

**Why:** Tests call `from solve import run; run()` and the working directory is not guaranteed to be `/app/`.

### 5.2 The `run()` Function Pattern

**Tests expect a callable `run()` function:**

```python
def run():
    # All operations go here
    BASE_DIR = Path(__file__).resolve().parent
    # ... rest of implementation ...

if __name__ == "__main__":
    run()
```

**Why:** Tests do `from solve import run; run()` to execute the solution.

### 5.3 Preservation and Consistency

**When updating existing artifacts:**
- Read the existing content first
- Modify in memory
- Write back the complete updated content
- Never overwrite blind

**When generating multiple outputs from the same source:**
- Extract facts once
- Use the same extracted values across all outputs
- Ensure consistency (e.g., dates in TXT must match dates in ICS)

**Example:**
```python
# Extract once
events = parse_calendar("calendar.ics")

# Use in multiple outputs
write_txt_summary("summary.txt", events)
write_ics_update("calendar.ics", events)  # preserves existing events
write_json_export("events.json", events)
```

### 5.4 Directory Creation

**Always create parent directories before writing:**

```python
output_path.parent.mkdir(parents=True, exist_ok=True)
with open(output_path, "w") as f:
    f.write(content)
```

### 5.5 Encoding

**Always specify encoding when writing text files:**

```python
with open(output_path, "w", encoding="utf-8") as f:
    f.write(content)
```

### 5.6 Edge Cases and Error Handling

**Robust solutions must handle these common edge cases:**

#### No Matching Results
```python
# When filtering produces no results
if not selected:
    # Decide based on task requirements:
    # - Write empty file
    # - Write file with just a newline
    # - Raise an error
    output_text = ""  # or "\n" depending on task spec
```

#### Malformed Input Files
```python
for file_path in files:
    try:
        # Parse file
        with open(file_path, "rb") as f:
            data = parse(f)
    except Exception as e:
        # Log warning but continue processing other files
        print(f"Warning: Could not parse {file_path.name}: {e}")
        continue
```

#### Missing Directories
```python
# Check if source directory exists
if not data_dir.exists():
    raise FileNotFoundError(f"Source directory not found: {data_dir}")

# Create output directory if needed
output_path.parent.mkdir(parents=True, exist_ok=True)
```

#### Missing Body Parts (Email)
```python
body_part = msg.get_body(preferencelist=("plain",))
if body_part is None:
    # No plain text part - skip or use alternative
    continue  # or try HTML part
```

#### Encoding Issues
```python
try:
    body = body_part.get_content()  # Auto-decodes charset
except (UnicodeDecodeError, LookupError):
    # Fallback to raw bytes or skip
    body = body_part.get_payload(decode=True).decode('utf-8', errors='replace')
```

#### Empty Output
```python
# When task requires output but no data matches
if not selected_items:
    # Check task requirements:
    # - Some tasks expect empty file
    # - Some expect file with headers only
    # - Some expect error
    output_text = ""  # Adjust based on task spec
```

**Best practices:**
- Always validate input exists before processing
- Use try-except for file parsing to handle malformed data
- Log warnings but continue processing when possible
- Check task requirements for empty result handling
- Test with edge cases: no matches, single match, all matches

## 6. Multi-Source Reconciliation and Cross-Output Consistency

**When tasks involve multiple source types or multiple outputs, you need architectural patterns beyond individual parsing and workflow recipes.**

### 6.1 Multi-Source Data Flow Patterns

**Pattern: Pipeline Architecture**
When combining data from multiple sources (e.g., emails + calendars + spreadsheets), use a pipeline structure:

```python
def run():
    BASE_DIR = Path(__file__).resolve().parent
    
    # Stage 1: Parse all sources into normalized intermediate format
    emails = parse_emails(BASE_DIR / "data" / "emails")
    calendars = parse_calendars(BASE_DIR / "data" / "calendars")
    spreadsheets = parse_spreadsheets(BASE_DIR / "data" / "tables")
    
    # Stage 2: Reconcile and merge data
    reconciled_data = reconcile_sources(emails, calendars, spreadsheets)
    
    # Stage 3: Apply workflow logic
    processed = apply_workflow(reconciled_data)
    
    # Stage 4: Generate all outputs from single source of truth
    write_txt_output(BASE_DIR / "data" / "summary.txt", processed)
    write_ics_output(BASE_DIR / "data" / "events.ics", processed)
    write_json_output(BASE_DIR / "data" / "export.json", processed)
```

**Key principle**: Parse once, reconcile once, generate all outputs from the same data structure.

### 6.2 Reconciliation Strategies

**Strategy 1: Union with Conflict Resolution**
When sources may contain overlapping or conflicting data:

```python
def reconcile_sources(emails, calendars, spreadsheets):
    # Build unified data structure
    events = {}
    
    # Add calendar events as base
    for cal_event in calendars:
        key = (cal_event["summary"], cal_event["dtstart"])
        events[key] = {
            "source": "calendar",
            "summary": cal_event["summary"],
            "dtstart": cal_event["dtstart"],
            "dtend": cal_event["dtend"],
            "description": cal_event.get("description", "")
        }
    
    # Merge email-derived events
    for email_event in emails:
        key = (email_event["summary"], email_event["dtstart"])
        if key in events:
            # Conflict: calendar already has this event
            # Strategy: prefer calendar, augment with email details
            events[key]["email_body"] = email_event.get("body", "")
        else:
            # New event from email
            events[key] = {
                "source": "email",
                "summary": email_event["summary"],
                "dtstart": email_event["dtstart"],
                "dtend": email_event.get("dtend", email_event["dtstart"]),
                "description": email_event.get("body", "")
            }
    
    return list(events.values())
```

**Strategy 2: Join on Common Keys**
When sources share identifiers (e.g., recipient email, event ID):

```python
def reconcile_by_recipient(emails, spreadsheets):
    # Group emails by recipient
    emails_by_recipient = defaultdict(list)
    for email in emails:
        emails_by_recipient[email["to"]].append(email)
    
    # Join with spreadsheet data
    reconciled = []
    for row in spreadsheets:
        recipient = row["email"]
        reconciled.append({
            "recipient": recipient,
            "metadata": row,  # From spreadsheet
            "emails": emails_by_recipient.get(recipient, [])  # From emails
        })
    
    return reconciled
```

### 6.3 Cross-Output Consistency

**Critical rule**: When generating multiple outputs, all outputs must be derived from the same data structure to ensure consistency.

**Anti-pattern** (leads to inconsistency):
```python
# BAD: Extract data separately for each output
def write_txt(emails):
    data = extract_from_emails(emails)  # Extract 1
    write_txt_file(data)

def write_ics(emails):
    data = extract_from_emails(emails)  # Extract 2 - may differ!
    write_ics_file(data)
```

**Correct pattern**:
```python
# GOOD: Extract once, use everywhere
def run():
    # Extract once
    processed_data = extract_and_process(emails)
    
    # Generate all outputs from same data
    write_txt(processed_data)
    write_ics(processed_data)
    write_json(processed_data)
```

**Consistency checklist**:
- [ ] All outputs use the same data structure
- [ ] Dates/times are formatted consistently across outputs
- [ ] Numerical values (counts, sums) agree across outputs
- [ ] Identifiers (IDs, names) match exactly across outputs
- [ ] If one output is updated, all outputs reflect the same change

### 6.4 Handling Multi-Source Edge Cases

**Missing sources**: Some sources may be absent or empty

```python
def reconcile_sources(emails, calendars, spreadsheets):
    # Handle missing sources gracefully
    if not emails:
        print("Warning: No email data found")
    if not calendars:
        print("Warning: No calendar data found")
    if not spreadsheets:
        print("Warning: No spreadsheet data found")
    
    # Continue with available sources
    available_sources = [s for s in [emails, calendars, spreadsheets] if s]
    if not available_sources:
        raise ValueError("No data sources available")
    
    # Reconcile available sources
    return merge_sources(available_sources)
```

**Conflicting data**: Different sources may disagree

```python
def resolve_conflicts(event_from_calendar, event_from_email):
    # Define conflict resolution strategy
    # Strategy 1: Prefer structured source (calendar) over unstructured (email)
    resolved = event_from_calendar.copy()
    
    # But augment with email details if calendar is missing them
    if not resolved.get("description") and event_from_email.get("body"):
        resolved["description"] = event_from_email["body"]
    
    return resolved
```

### 6.5 Example: Email + Calendar → TXT + ICS

**Task**: Read emails about meetings, read calendar, find conflicts, write summary (TXT) and updated calendar (ICS)

```python
from pathlib import Path
from email import policy
from email.parser import BytesParser
from icalendar import Calendar, Event
from datetime import datetime, timedelta


def run():
    BASE_DIR = Path(__file__).resolve().parent
    
    # Stage 1: Parse all sources
    email_meetings = parse_email_meetings(BASE_DIR / "data" / "emails")
    calendar_events = parse_calendar(BASE_DIR / "data" / "calendar.ics")
    
    # Stage 2: Reconcile - find conflicts
    conflicts = find_conflicts(email_meetings, calendar_events)
    
    # Stage 3: Generate outputs from single source of truth
    write_conflict_summary(BASE_DIR / "data" / "conflicts.txt", conflicts)
    write_updated_calendar(BASE_DIR / "data" / "calendar.ics", 
                          calendar_events, email_meetings)


def parse_email_meetings(email_dir):
    meetings = []
    for eml_path in email_dir.glob("*.eml"):
        with open(eml_path, "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)
        if "meeting" in msg["Subject"].lower():
            body = msg.get_body(preferencelist=("plain",)).get_content()
            # Extract meeting details from body
            meeting = extract_meeting_details(body, msg["Subject"])
            meetings.append(meeting)
    return meetings


def parse_calendar(ics_path):
    with open(ics_path, "rb") as f:
        cal = Calendar.from_ical(f.read())
    events = []
    for component in cal.walk():
        if component.name == "VEVENT":
            events.append({
                "summary": str(component.get("SUMMARY")),
                "dtstart": component.get("DTSTART").dt,
                "dtend": component.get("DTEND").dt
            })
    return events


def find_conflicts(email_meetings, calendar_events):
    conflicts = []
    for meeting in email_meetings:
        for event in calendar_events:
            if times_overlap(meeting["dtstart"], meeting["dtend"],
                           event["dtstart"], event["dtend"]):
                conflicts.append({
                    "email_meeting": meeting,
                    "calendar_event": event
                })
    return conflicts


def write_conflict_summary(output_path, conflicts):
    lines = ["Meeting Conflicts:", ""]
    for i, conflict in enumerate(conflicts, 1):
        lines.append(f"{i}. {conflict['email_meeting']['summary']}")
        lines.append(f"   Conflicts with: {conflict['calendar_event']['summary']}")
        lines.append(f"   Time: {conflict['email_meeting']['dtstart']}")
        lines.append("")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_updated_calendar(output_path, existing_events, new_events):
    cal = Calendar()
    cal.add("prodid", "-//Office Workflow//EN")
    cal.add("version", "2.0")
    
    # Add existing events (preserve)
    for event_data in existing_events:
        event = Event()
        event.add("summary", event_data["summary"])
        event.add("dtstart", event_data["dtstart"])
        event.add("dtend", event_data["dtend"])
        cal.add_component(event)
    
    # Add new events from emails
    for event_data in new_events:
        event = Event()
        event.add("summary", event_data["summary"])
        event.add("dtstart", event_data["dtstart"])
        event.add("dtend", event_data["dtend"])
        cal.add_component(event)
    
    with open(output_path, "wb") as f:
        f.write(cal.to_ical())


def times_overlap(start1, end1, start2, end2):
    return start1 < end2 and start2 < end1


def extract_meeting_details(body, subject):
    # Extract dates/times from email body
    import re
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', body)
    times = re.findall(r'\d{1,2}:\d{2}', body)
    # ... parse into datetime objects ...
    return {
        "summary": subject,
        "dtstart": datetime.now(),  # placeholder
        "dtend": datetime.now() + timedelta(hours=1)
    }
```

## 7. Implementation Checklist

Before finalizing your solution:

- [ ] **Decomposed the task** into 5 dimensions (sources, relation, destinations, constraints, preservation)
- [ ] **Path resolution**: Using `Path(__file__).resolve().parent` to anchor paths
- [ ] **Callable function**: Defined `def run():` that performs all operations
- [ ] **Imports**: All necessary imports at the top of `solve.py`
- [ ] **Source parsing**: Using correct library and pattern for each source type
- [ ] **Workflow logic**: Implemented the correct relation (filtering, scheduling, etc.)
- [ ] **Output format**: Verified exact formatting (separators, trailing newlines, structure)
- [ ] **Encoding**: Specified `encoding="utf-8"` when writing text files
- [ ] **Directory creation**: Used `mkdir(parents=True, exist_ok=True)` before writing
- [ ] **Sorting**: Applied sorting criteria specified in the task
- [ ] **Preservation**: Verified that source content is preserved exactly as required
- [ ] **Consistency**: Checked that facts agree across multiple outputs
- [ ] **Edge cases**: Handled no-match scenarios, malformed files, missing directories (see §5.6)
- [ ] **Multi-source**: If multiple sources, used pipeline architecture and reconciliation (see §6)
- [ ] **Cross-output**: If multiple outputs, all derived from single source of truth (see §6.3)

## 8. Testing Strategy

**Since tests are injected during evaluation, verify manually:**

```python
# Test the import pattern
from solve import run
run()

# Verify output exists
assert output_path.exists()

# Verify format
with open(output_path, "r", encoding="utf-8") as f:
    content = f.read()
    print(repr(content))  # Check exact formatting

# Verify specific requirements
assert content.endswith("\n")  # Ends with one newline
assert not content.startswith("\n")  # No leading blank line
```

## 9. Common Failure Modes

1. **Path resolution failure**: Using relative paths without anchoring to script location
2. **MIME parsing errors**: Opening email files in text mode, not using `policy.default`, or not handling multipart correctly
3. **Body content stripping**: Accidentally removing embedded metadata that is part of the body
4. **Output formatting errors**: Wrong number of blank lines, missing trailing newline, extra leading newline
5. **Import errors**: Forgetting to import required libraries in `solve.py`
6. **Encoding issues**: Not specifying `encoding="utf-8"` when writing files
7. **Sorting errors**: Not sorting by the correct criterion
8. **Preservation violations**: Overwriting existing content instead of updating
9. **Inconsistency**: Facts disagreeing across multiple outputs
10. **Multi-source reconciliation failure**: Not merging data from multiple sources correctly, leading to duplicates or missing data
11. **Cross-output inconsistency**: Generating multiple outputs from separate data extractions, causing values to disagree
12. **Conflict resolution errors**: Not handling conflicting data from different sources according to task requirements

## 10. Worked Example: v01 Email Filtering Task

**Task:** Read `.eml` files, filter by Subject, write formatted TXT output

**Decomposition:**
- Sources: `.eml` files in `data/emails/Bob/`
- Relation: Relevance filtering (Subject ∈ {"scheduled meeting", "application approved"})
- Destinations: `data/answer.txt` with formatted blocks
- Constraints: Sort by filename
- Preservation: Complete body text including "Sent at:" lines

**Solution:**
```python
from pathlib import Path
from email import policy
from email.parser import BytesParser


def run():
    BASE_DIR = Path(__file__).resolve().parent
    data_dir = BASE_DIR / "data" / "emails" / "Bob"
    output_path = BASE_DIR / "data" / "answer.txt"

    TARGET_SUBJECTS = {"scheduled meeting", "application approved"}

    # Read and filter emails
    selected = []
    for eml_path in sorted(data_dir.glob("*.eml")):
        with open(eml_path, "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)
        subject = msg["Subject"]
        if subject in TARGET_SUBJECTS:
            body_part = msg.get_body(preferencelist=("plain",))
            body = body_part.get_content().strip()
            selected.append((eml_path.name, subject, body))

    # Build output
    blocks = []
    for _fname, subject, body in selected:
        blocks.append(f"Subject: {subject}\n{body}")

    output_text = "\n\n".join(blocks) + "\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)


if __name__ == "__main__":
    run()
```

**Key decisions:**
- Used `sorted(data_dir.glob("*.eml"))` to sort by filename
- Used `policy.default` for modern email handling
- Used `get_body(preferencelist=("plain",))` to extract plain text
- Preserved complete body including "Sent at:" lines
- Formatted blocks with `\n\n` separator and trailing `\n`

## 11. Generalization Strategy

When encountering a new office-workflow task:

1. **Map to the five dimensions**: Identify source artifacts, workflow relation, destination artifacts, constraints, and preservation requirements
2. **Select parsing strategy**: Choose the appropriate parser for each source artifact type (Section 2)
3. **Implement workflow logic**: Apply the transformation that connects source to destination (Section 3)
4. **Generate destination**: Use the appropriate library to create output in the required format (Section 4)
5. **Verify constraints**: Check that temporal, routing, and preservation constraints are satisfied (Section 5)
6. **Test manually**: Run the solution and verify output format, content, and consistency (Section 7)

**Remember:** The specific file types, workflow operations, and output formats will vary, but the abstract structure (source → workflow → destination with constraints) remains constant across the entire family.
