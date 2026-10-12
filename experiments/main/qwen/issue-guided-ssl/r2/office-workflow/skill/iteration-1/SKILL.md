---
name: office-workflow
description: Reusable patterns for processing office artifacts (MIME emails, calendars, documents) through filtering, extraction, transformation, and routing workflows with temporal and consistency constraints.
---

# Office Workflow Skill

This skill encodes reusable patterns for processing office artifacts through structured workflows. The core technical foundation is MIME email parsing, which generalizes to calendar processing, document extraction, and multi-format output generation.

## Core Pattern: MIME Email Body Extraction

When processing `.eml` files, use this pattern to extract plain-text bodies from multipart MIME messages:

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
