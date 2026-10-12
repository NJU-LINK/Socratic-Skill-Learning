---
name: office-workflow
description: >
  Reusable agent skill for office-workflow tasks: reading heterogeneous office
  artifacts (MIME email, iCalendar, PDF, XLSX), filtering by relevance
  criteria, extracting structured content, formatting destination artifacts
  (TXT, ICS, DOCX, PDF, JSON, EML), and routing outputs with consistency
  guarantees. Covers the read→filter→extract→format→route pipeline.
---

# Office-Workflow Family Skill

## 1. Family Workflow Pattern

Every task in this family follows the same five-stage pipeline:

1. **Read** — Parse source artifacts using format-appropriate libraries (MIME email via `email`, iCalendar via `icalendar`, PDF via `pymupdf`/`pdfplumber`, XLSX via `openpyxl`/`pandas`).
2. **Filter** — Select relevant items by exact-match criteria (subject, recipient, class membership, date range, etc.). Use strict equality, never substring or fuzzy matching, unless the task explicitly requests it.
3. **Extract** — Pull structured content from selected items (headers, bodies, table rows, calendar events, quantitative data).
4. **Format** — Materialize destination artifacts in the required format (TXT, ICS, JPEG, DOCX, EML, PDF, JSON).
5. **Route** — Write outputs to specified paths, preserving existing content and maintaining cross-output consistency.

## 2. MIME Email Body Extraction

This is the most error-prone mechanism in the family. An `.eml` file is a MIME message that may be multipart.

### Critical Rules

- **Never call `.strip()` on `msg.get_payload()` directly** — for multipart messages it returns a list, not a string.
- **Always use `decode=True`** when calling `get_payload()` to handle transfer encodings (base64, quoted-printable, 7bit).
- **Always walk the MIME tree** to find `text/plain` parts, since the top-level message may be `multipart/mixed`, `multipart/alternative`, etc.
- **Strip the final body text** — MIME bodies often have trailing newlines.

### Reference Implementation

```python
import email
from pathlib import Path

def extract_plain_text_body(msg):
    """Extract plain-text body from a MIME message, handling multipart correctly."""
    bodies = []
    for part in msg.walk():
        if part.get_content_type() == 'text/plain':
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            bodies.append(payload.decode(charset))
    
    if bodies:
        return bodies[0].strip()
    
    return ""

def parse_eml_file(path):
    """Parse an .eml file into an email Message object."""
    with open(path, "rb") as f:
        return email.message_from_bytes(f.read())
```

### Modern API Alternative (Python 3.6+)

If using the new `EmailMessage` API (via `policy=email.policy.default`), you can use `msg.get_body()` and `part.get_content()`:

```python
import email
from email import policy

def parse_eml_modern(path):
    with open(path, "rb") as f:
        return email.message_from_bytes(f.read(), policy=policy.default)

def extract_body_modern(msg):
    body_part = msg.get_body(preferencelist=('plain',))
    if body_part:
        return body_part.get_content().strip()
    return ""
```

**Note**: The legacy `Message` class (from `message_from_bytes` without a policy) does NOT have `get_body()`. Use the walk-based approach for maximum compatibility.

## 3. Exact-Match Filtering Principle

When tasks specify filtering criteria (subject, recipient, filename, class membership), use **exact equality** unless the task explicitly states otherwise.

### Common Pitfalls

- **Filename vs. Header mismatch**: An email file named `scholarship approved.eml` may have Subject `application approved`. Always check the actual header/content, not the filename.
- **Case sensitivity**: `Subject: Scheduled Meeting` is NOT the same as `scheduled meeting` unless the task says case-insensitive.
- **Whitespace**: Headers may have leading/trailing whitespace. Strip before comparison if the task doesn't specify exact byte matching.

### Pattern

```python
target_values = {"exact value 1", "exact value 2"}
if actual_value in target_values:
    # selected
```

## 4. Output Formatting Discipline

### Text Output (TXT)

- Each record/block: `Subject: <value>\n<body>\n`
- Adjacent blocks separated by **one blank line** (`\n\n`)
- File ends with **exactly one newline** (not zero, not two)
- Records sorted by the criterion specified (usually source filename)

### Pattern

```python
blocks = [f"Subject: {subj}\n{body}" for subj, body in selected]
output = "\n\n".join(blocks) + "\n"
Path("output.txt").write_text(output)
```

### Calendar Output (ICS)

- Preserve existing events when updating a calendar
- Use proper iCalendar format with VCALENDAR/VEVENT wrappers
- Ensure timezone consistency

### Structured Output (JSON)

- Validate JSON structure matches specification
- Ensure numeric fields are numbers, not strings
- Maintain consistent key naming

## 5. Preservation and Consistency

### Cross-Output Consistency

When a task produces multiple outputs (e.g., a PDF and an email, or a TXT and an ICS), facts that appear in both must be **identical**:
- Same dates, times, names, quantities
- Same formatting conventions
- No contradictions between outputs

### Source Preservation

- Never modify source artifacts unless explicitly instructed
- When "updating" a calendar, preserve all existing events not affected by the task
- When filtering emails, the original files remain unchanged

## 6. Routing Rules

### One-Output-Per-Source

When each source item produces one output:
- Sort outputs by source identifier (filename, ID, etc.)
- Use consistent naming conventions

### Recipient-Based Routing

When outputs are routed to specific recipients:
- Create recipient-specific directories/files
- Include only that recipient's relevant data
- Maintain individualized facts across paired outputs

## 7. Variation Dimensions

According to the family spec, tasks may vary along these axes:

- **Workflow relation**: relevance filtering, scheduling, extraction, analysis, summarization, notification, routing
- **Source artifacts**: email, calendar, PDF, XLSX, or combinations
- **Destination artifacts**: TXT, ICS, JPEG, DOCX, EML, PDF, JSON
- **Constraints**: recipient identity, subject relevance, class membership, duplicates, time windows
- **Preservation**: source integrity, cross-output fact consistency

Adapt the pipeline stages to the specific combination, but the underlying pattern remains constant.
