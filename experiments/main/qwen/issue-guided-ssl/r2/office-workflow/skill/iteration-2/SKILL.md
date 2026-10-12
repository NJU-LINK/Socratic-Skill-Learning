---
name: office-workflow
description: Reusable patterns for processing office artifacts (MIME emails, calendars, documents, spreadsheets) through filtering, extraction, transformation, routing, and scheduling workflows with temporal and consistency constraints.
---

# Office Workflow Skill

This skill encodes reusable patterns for processing office artifacts through structured workflows. It covers MIME email parsing, iCalendar processing, spreadsheet analysis, and multi-format output generation.

## Dependencies

Before implementing any workflow, ensure required packages are installed. Python standard library modules are always available; third-party packages must be installed explicitly.

### Standard Library (no installation needed)
- `email`, `email.policy` — MIME email parsing
- `json` — JSON output
- `pathlib` — File path operations
- `datetime` — Date/time handling
- `csv` — CSV processing
- `subprocess`, `sys` — Process management and dependency installation

### Third-Party Packages (install before use)

**iCalendar workflows:**
```bash
pip install icalendar
```

**XLSX spreadsheet workflows:**
```bash
pip install openpyxl
```

**PDF processing:**
```bash
pip install PyPDF2          # Reading existing PDFs
pip install pdfminer.six    # Extracting text from PDFs
pip install reportlab       # Generating PDFs
```

**DOCX document workflows:**
```bash
pip install python-docx
```

**Visualization (JPEG output):**
```bash
pip install matplotlib
```

### Auto-Install Pattern

Include this pattern in solve.py for workflows using third-party packages:

```python
import subprocess
import sys

def ensure_dependencies(packages):
    """Install required third-party packages if not already available."""
    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

# Example usage at the start of run():
# ensure_dependencies(['icalendar', 'openpyxl'])
```

Or install inline before importing:

```python
def run():
    import subprocess, sys
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'icalendar', '-q'])
    from icalendar import Calendar
    # ... rest of workflow
```

**Always run `pip install <package>` before using third-party imports in solve.py.**

## Core Pattern: MIME Email Body Extraction

When processing `.eml` files, use this pattern to extract plain-text bodies from multipart MIME messages. This uses only stdlib modules (`email`, `email.policy`) — no installation needed.

```python
import email
import email.policy

def extract_text_body(msg):
    """Extract the text/plain body from a MIME email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or 'us-ascii'
                    return payload.decode(charset).strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or 'us-ascii'
            return payload.decode(charset).strip()
    return ""
```

**Why this matters:** Calling `msg.get_payload()` on a multipart message returns a list of Message parts, not a string. You must walk the MIME structure to find the `text/plain` part, decode it with the correct charset, and extract the content.

### Parsing with email.policy

Use `email.policy.default` for robust MIME header decoding:

```python
with open(eml_path, 'rb') as f:
    msg = email.message_from_binary_file(f, policy=email.policy.default)
```

This automatically handles MIME-encoded subject headers and other encoded fields.

## Core Pattern: iCalendar Processing

When processing `.ics` calendar files, use the `icalendar` library. **Requires `pip install icalendar` before use.**

```python
from icalendar import Calendar
from datetime import datetime
from pathlib import Path

def parse_calendar_events(ics_path):
    """Parse iCalendar file and extract events with start/end times."""
    with open(ics_path, 'rb') as f:
        cal = Calendar.from_ical(f.read())
    
    events = []
    for component in cal.walk():
        if component.name == 'VEVENT':
            dtstart = component.get('dtstart').dt
            dtend = component.get('dtend').dt
            summary = str(component.get('summary', ''))
            
            # Convert date to datetime if needed
            if not isinstance(dtstart, datetime):
                dtstart = datetime.combine(dtstart, datetime.min.time())
            if not isinstance(dtend, datetime):
                dtend = datetime.combine(dtend, datetime.min.time())
            
            events.append({
                'summary': summary,
                'start': dtstart,
                'end': dtend,
                'uid': str(component.get('uid', ''))
            })
    
    return events
```

### Generating iCalendar Output

To create calendar files with events:

```python
from icalendar import Calendar, Event
from datetime import datetime

def create_calendar_event(summary, dtstart, dtend, uid=None):
    """Create a VEVENT component."""
    event = Event()
    event.add('summary', summary)
    event.add('dtstart', dtstart)
    event.add('dtend', dtend)
    if uid:
        event.add('uid', uid)
    return event

def write_calendar(events, output_path):
    """Write events to an ICS file."""
    cal = Calendar()
    cal.add('prodid', '-//Office Workflow//EN')
    cal.add('version', '2.0')
    
    for evt in events:
        event = create_calendar_event(
            evt['summary'],
            evt['start'],
            evt['end'],
            evt.get('uid')
        )
        cal.add_component(event)
    
    with open(output_path, 'wb') as f:
        f.write(cal.to_ical())
```

### Finding Common Free Time

To find available time slots across multiple calendars:

```python
from datetime import timedelta

def find_free_time(calendars, search_start, search_end, min_duration=timedelta(hours=1)):
    """Find common free time across multiple calendars."""
    # Collect all busy intervals
    busy_intervals = []
    for cal_path in calendars:
        events = parse_calendar_events(cal_path)
        for evt in events:
            busy_intervals.append((evt['start'], evt['end']))
    
    # Sort by start time
    busy_intervals.sort(key=lambda x: x[0])
    
    # Find gaps
    free_slots = []
    current_time = search_start
    
    for busy_start, busy_end in busy_intervals:
        if busy_start > current_time:
            gap_duration = busy_start - current_time
            if gap_duration >= min_duration:
                free_slots.append((current_time, busy_start))
        current_time = max(current_time, busy_end)
    
    # Check final gap
    if search_end - current_time >= min_duration:
        free_slots.append((current_time, search_end))
    
    return free_slots
```

## Core Pattern: XLSX Spreadsheet Processing

When processing `.xlsx` files, use `openpyxl`. **Requires `pip install openpyxl` before use.**

```python
from openpyxl import load_workbook
from pathlib import Path

def read_spreadsheet_table(xlsx_path, sheet_name=None):
    """Read spreadsheet data as list of dictionaries."""
    wb = load_workbook(xlsx_path, read_only=True)
    
    if sheet_name:
        ws = wb[sheet_name]
    else:
        ws = wb.active
    
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    
    if not rows:
        return []
    
    # First row is headers
    headers = [str(h).strip() if h else f'col_{i}' for i, h in enumerate(rows[0])]
    
    # Convert to list of dicts
    data = []
    for row in rows[1:]:
        if any(cell is not None for cell in row):
            record = {}
            for i, value in enumerate(row):
                if i < len(headers):
                    record[headers[i]] = value
            data.append(record)
    
    return data
```

### Deduplicating Spreadsheet Rows

```python
def deduplicate_rows(data, key_fields):
    """Remove duplicate rows based on key fields."""
    seen = set()
    unique = []
    
    for row in data:
        key = tuple(row.get(field) for field in key_fields)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    
    return unique
```

## General Workflow Pattern

Most office workflows follow this structure:

1. **Collect artifacts**: Use `Path.glob()` to find input files
2. **Sort deterministically**: Sort by filename or other stable key
3. **Filter by criteria**: Apply exact-match or pattern-based filters
4. **Extract/transform**: Parse content and apply transformations
5. **Format output**: Generate structured output with consistent formatting

### Example: Subject-Based Email Filtering

```python
from pathlib import Path

def filter_emails_by_subject(email_dir, target_subjects):
    """Filter emails by exact subject match."""
    eml_files = sorted(Path(email_dir).glob('*.eml'), key=lambda p: p.name)
    
    results = []
    for eml_path in eml_files:
        with open(eml_path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=email.policy.default)
        
        subject = msg.get('Subject', '')
        if subject in target_subjects:
            body = extract_text_body(msg)
            results.append({
                'filename': eml_path.name,
                'subject': subject,
                'body': body
            })
    
    return results
```

## Output Formatting

When generating structured text output:

- **Block format**: Each item becomes a block with headers and content
- **Separation**: Use blank lines (`\n\n`) between blocks
- **Termination**: End file with exactly one newline
- **Consistency**: Ensure all blocks follow the same structure

```python
blocks = []
for item in items:
    block = f"Subject: {item['subject']}\n{item['body']}"
    blocks.append(block)

output = '\n\n'.join(blocks) + '\n'
```

### JSON Output

For machine-readable output:

```python
import json

def write_json_output(data, output_path):
    """Write structured data as JSON."""
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
```

## Multi-Artifact Reconciliation

When combining data from multiple artifact types:

1. **Extract facts from each source**: Parse emails, calendars, spreadsheets separately
2. **Normalize timestamps**: Convert all dates to datetime objects with consistent timezone
3. **Match by key fields**: Use unique identifiers (UID, subject, ID) to correlate records
4. **Resolve conflicts**: When facts disagree, prefer the most recent or most specific source
5. **Preserve originals**: Never modify source artifacts; create new outputs

```python
def reconcile_email_calendar_data(emails, events):
    """Match emails to calendar events by subject/summary."""
    email_by_subject = {e['subject']: e for e in emails}
    event_by_summary = {ev['summary']: ev for ev in events}
    
    reconciled = []
    for subject, email in email_by_subject.items():
        if subject in event_by_summary:
            event = event_by_summary[subject]
            reconciled.append({
                'subject': subject,
                'email_body': email['body'],
                'event_start': event['start'],
                'event_end': event['end']
            })
    
    return reconciled
```

## Per-Recipient Routing

When generating individualized outputs for multiple recipients:

```python
from pathlib import Path

def route_outputs_by_recipient(data, output_dir, template_func):
    """Generate per-recipient output files."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Group data by recipient
    by_recipient = {}
    for item in data:
        recipient = item.get('recipient')
        if recipient:
            by_recipient.setdefault(recipient, []).append(item)
    
    # Generate output for each recipient
    for recipient, items in by_recipient.items():
        output_path = output_dir / f"{recipient}.txt"
        content = template_func(items)
        with open(output_path, 'w') as f:
            f.write(content)
```

## Variation Dimensions

This skill family spans multiple workflow types:

### Relation Types
- **Relevance filtering**: Select artifacts matching criteria (subject, sender, date)
- **Conflict-free scheduling**: Find common free time across calendars
- **Fact extraction**: Pull structured data from unstructured content
- **Quantitative analysis**: Compute statistics and generate visualizations
- **Summarization**: Condense content while preserving key facts
- **Notification/routing**: Direct outputs to recipients based on rules

### Source Artifacts
- MIME email (`.eml`) with multipart structures
- iCalendar (`.ics`) with VEVENT/VTODO components
- PDF documents with text and tables
- XLSX spreadsheets with structured data
- Combinations requiring cross-artifact reconciliation

### Destination Artifacts
- Plain text (`.txt`) with structured formatting
- iCalendar (`.ics`) for calendar updates
- Images (`.jpeg`) for visualizations
- Documents (`.docx`, `.pdf`) for formatted output
- Email (`.eml`) for notifications
- Structured JSON for machine-readable output

### Temporal and Routing Constraints
- Recipient identity (route to specific people)
- Subject-based relevance (filter by content)
- Class membership (group by category)
- Duplicate handling (deduplicate source rows)
- Common free-time windows (schedule conflicts)
- One-output-per-message or one-output-per-recipient routing

### Preservation and Consistency
- Original calendar events must remain intact
- Extracted facts must agree across outputs
- Recipient folder names must match routing rules
- Individualized facts must repeat consistently across paired artifacts

## Implementation Checklist

When implementing an office workflow:

- [ ] Use `email.policy.default` for MIME parsing
- [ ] Walk multipart structure to extract text/plain bodies
- [ ] Decode payloads with correct charset (default to 'us-ascii')
- [ ] Strip whitespace from extracted content
- [ ] Sort inputs deterministically before processing
- [ ] Use exact-match comparison for filtering (not substring)
- [ ] Format output blocks consistently with proper separators
- [ ] End output files with exactly one newline
- [ ] Preserve source artifacts unchanged
- [ ] Ensure facts are consistent across all outputs
- [ ] For iCalendar: use `icalendar` library, handle date vs datetime
- [ ] For XLSX: use `openpyxl`, treat first row as headers
- [ ] For scheduling: normalize all timestamps to datetime objects
- [ ] For routing: group by recipient, generate individualized outputs
- [ ] For reconciliation: match by unique identifiers, resolve conflicts
