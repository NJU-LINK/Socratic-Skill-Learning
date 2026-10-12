---
name: office-workflow
description: >
  Generalized skill for office-workflow tasks: discover and parse source
  artifacts (MIME email, iCalendar, PDF, XLSX), apply selection predicates
  (subject match, date range, relevance, class membership), extract structured
  content (headers, bodies, tables, dates, quantities), transform/route/format
  into destination artifacts (TXT, ICS, DOCX, PDF, JSON, EML), and preserve
  consistency across paired outputs.
---

# Office Workflow Skill

## Overview

Every task in this family follows the same five-step skeleton:

1. **Discover & parse source artifacts** — find files, parse them with the right library
2. **Apply a selection predicate** — filter by subject, date, recipient, relevance, etc.
3. **Extract structured content** — headers, bodies, table cells, dates, quantities
4. **Transform / route / format** — produce destination artifacts in the required format
5. **Preserve consistency** — ensure facts agree across paired outputs; don't mutate sources

The parsing infrastructure is stable across family members. The predicate logic, extraction targets, and output formatting are the axes that vary per spec.yaml.

## Quick Start: Minimal Working Example

This skill is **self-contained**. The patterns below are sufficient to solve most family members. Reference files in `references/` provide additional examples but are not required.

*The following is a minimal working pattern for the most common variant (email → TXT). **Read the task instruction carefully and adapt ALL paths, predicates, and output format to your specific problem.** The placeholder values below are examples only.*

### Email → TXT (most common pattern)

```python
import email
import os
import glob
from email import policy

def run():
    # CWD robustness
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    # TODO: Adapt these to your task
    emails_dir = "data/emails/<RECIPIENT>/"  # Check task for actual path
    output_file = "data/answer.txt"  # Check task for actual output file
    target_subjects = {"<SUBJECT_1>", "<SUBJECT_2>"}  # Check task for actual subjects
    
    selected = []
    
    for fpath in sorted(glob.glob(os.path.join(emails_dir, "*.eml"))):
        with open(fpath, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        
        subject = msg["subject"]
        if subject and subject in target_subjects:
            # Extract plain-text body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_content()
                        break
            else:
                body = msg.get_content()
            
            selected.append((os.path.basename(fpath), subject, body.strip()))
    
    # Sort and write output
    selected.sort(key=lambda x: x[0])  # Adapt sort key if needed
    blocks = [f"Subject: {subj}\n{body}" for _, subj, body in selected]
    
    with open(output_file, "w") as f:
        f.write("\n\n".join(blocks) + "\n")
```

**Key patterns:**
- Use `policy.default` for automatic encoding handling
- Check `subject and subject in target_set` to handle None
- Strip body text with `.strip()`
- Separate blocks with `\n\n`, end file with `\n`
- **Replace all `<PLACEHOLDER>` values with actual task requirements**

## Decision Procedure

When you encounter a new task, answer these questions in order:

### 1. What are the source artifacts?

| Source type | Library | Key pattern |
|---|---|---|
| `.eml` (MIME email) | `email` (stdlib) + `policy.default` | `email.message_from_binary_file(f, policy=policy.default)` |
| `.ics` (iCalendar) | `icalendar` | `Calendar.from_ical(data)`, iterate `VEVENT`/`VTODO` |
| `.xlsx` (Excel) | `openpyxl` | `wb.load_workbook(path)`, iterate `ws.iter_rows()` |
| `.pdf` | `PyPDF2` or `pdfplumber` | `PdfReader(path)`, extract text per page |

### 2. What is the selection predicate?

Common predicates from the spec:
- **Exact subject match**: `msg["subject"] in target_set` (case-sensitive on value)
- **Subject contains/starts-with**: normalize both sides, use `in` or `.startswith()`
- **Date range**: parse `Sent at:` lines or `Date:` headers, compare with `datetime`
- **Recipient-based routing**: match `To:` / `From:` against recipient list
- **Class membership**: check if entity belongs to a group (e.g., student in class)
- **Duplicate detection**: track seen keys in a set

### 3. What content must be extracted?

- **Email**: Subject header, plain-text body (walk multipart for `text/plain`)
- **Calendar**: Event summary, start/end times, location, attendees
- **Spreadsheet**: Specific columns/rows, numeric values for analysis
- **PDF**: Text blocks, tables, dates

### 4. What is the destination format?

| Destination | Library | Key pattern |
|---|---|---|
| `.txt` | stdlib `open()` | Write formatted blocks, separate with blank lines |
| `.ics` | `icalendar` | Create `Event` objects, add to `Calendar`, serialize |
| `.docx` | `python-docx` | `Document()`, add paragraphs/tables |
| `.pdf` | `reportlab` or `fpdf` | Create PDF, add text/images |
| `.eml` | `email` (stdlib) | Construct `MIMEMultipart`, set headers, serialize |
| `.json` | `json` (stdlib) | `json.dumps(data, indent=2)` |
| In-place calendar update | `icalendar` | Parse existing ICS, add/remove events, rewrite |

### 5. What consistency constraints apply?

- **Preserve sources**: never modify original `.eml`, `.ics`, `.xlsx` files
- **Cross-output agreement**: if the same fact appears in both a PDF and an email, they must match exactly
- **Ordering**: sort outputs as specified (by filename, date, subject, etc.)
- **One-output-per-X**: respect routing constraints (per message, per recipient, per class)

## Email Parsing Deep-Dive

Since MIME email is the most common source type, here are the critical patterns and pitfalls:

### Parsing with policy.default

```python
import email
from email import policy

with open(path, "rb") as f:
    msg = email.message_from_binary_file(f, policy=policy.default)
```

**Why `policy.default`?** It automatically handles:
- Transfer encodings (7bit, quoted-printable, base64) via `.get_content()`
- RFC 2047 encoded words in headers (`=?utf-8?b?...?=`) — `msg["subject"]` returns decoded string
- Charset conversion for text parts

### Extracting plain-text body from multipart

```python
body = ""
if msg.is_multipart():
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            body = part.get_content()  # returns str with policy.default
            break
else:
    body = msg.get_content()
```

**Pitfall**: `multipart/alternative` may contain both `text/plain` and `text/html`. If a task needs the "best" plain text, prefer `text/plain` explicitly. For nested multipart, `walk()` traverses all levels.

### Header access

- `msg["subject"]` — case-insensitive header name lookup, returns string or None
- Header **value** comparison is case-sensitive: normalize both sides if fuzzy matching needed
- `msg["date"]`, `msg["from"]`, `msg["to"]` — same pattern

### get_content() vs get_payload(decode=True)

With `policy.default`, `.get_content()` returns `str` for text parts and `bytes` for binary. With legacy policy, `.get_payload(decode=True)` returns bytes. Always prefer `policy.default` + `.get_content()`.

## Output Formatting Patterns

### TXT output (most common for v01-style tasks)

```python
blocks = []
for item in selected:
    block = f"Subject: {item.subject}\n{item.body}"
    blocks.append(block)

with open(output_path, "w") as f:
    f.write("\n\n".join(blocks) + "\n")
```

**Critical details**:
- Separate adjacent blocks with exactly one blank line (`\n\n`)
- End the file with exactly one newline (`\n`)
- Strip body text (remove leading/trailing whitespace)
- Do not include headers/body from non-selected messages

### ICS output

```python
from icalendar import Calendar, Event
from datetime import datetime

cal = Calendar()
cal.add("prodid", "-//My Product//EN")
cal.add("version", "2.0")

for item in selected:
    event = Event()
    event.add("summary", item.summary)
    event.add("dtstart", item.start)
    event.add("dtend", item.end)
    cal.add_component(event)

with open(output_path, "wb") as f:
    f.write(cal.to_ical())
```

## Worked v01 Example

The v01 task: parse `.eml` files in `data/emails/Bob/`, select messages with Subject exactly `scheduled meeting` or `application approved`, sort by filename, write `data/answer.txt` with formatted blocks.

The **Quick Start** section above contains the complete working solution for v01. Key decisions:
- Used `policy.default` for automatic decoding
- Walked multipart to find `text/plain` part
- Stripped body text
- Sorted by filename (alphabetical)
- Formatted as `Subject: <subject>\n<body>` blocks separated by blank lines
- Ended file with single newline

For additional examples and variations, see `references/v01-solution.py` (supplementary).

## Operational Details

### CWD Robustness

The test harness calls `from solve import run; run()` with whatever CWD the test process has (typically `/app`). To make solutions robust regardless of CWD, add this defensive pattern at the top of `run()`:

```python
import os

def run():
    # Ensure we're in the right working directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    # ... rest of solution
```

This ensures relative paths like `data/emails/Bob/` work correctly even if the test harness runs from a different directory.

## Generalization Checklist

When adapting to a new family member, verify:

- [ ] Source artifact type identified → correct parser selected
- [ ] Selection predicate implemented (exact match, contains, date range, etc.)
- [ ] Extraction targets identified (which headers, which body parts, which cells)
- [ ] Destination format determined → correct writer selected
- [ ] Consistency constraints checked (preserve sources, cross-output agreement)
- [ ] Output ordering matches specification
- [ ] Byte-level output verified (trailing newlines, blank line separators, encoding)
- [ ] CWD robustness ensured (os.chdir pattern if needed)
