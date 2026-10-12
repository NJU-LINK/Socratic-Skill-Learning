# Email Parsing Reference

## Always use policy.default

```python
import email
from email import policy

with open(path, "rb") as f:
    msg = email.message_from_binary_file(f, policy=policy.default)
```

This single choice resolves most encoding headaches:
- Transfer encodings (base64, quoted-printable, 7bit) are decoded automatically
- RFC 2047 header encoding (`=?utf-8?b?...?=`, `=?iso-8859-1?q?...?=`) is decoded
- Charset conversion for text parts is handled
- `.get_content()` returns `str` for text, `bytes` for binary

## Header access patterns

```python
# Case-insensitive header name lookup
msg["subject"]   # == msg["Subject"] == msg["SUBJECT"]
msg["from"]
msg["to"]
msg["date"]
msg["message-id"]

# Returns None if header is absent
subject = msg["subject"]  # str or None

# For multiple same-name headers (e.g., Received)
msg.get_all("received")  # list of values
```

**Important**: Header *name* lookup is case-insensitive, but header *value* comparison is case-sensitive.

```python
# Case-sensitive (exact match)
if msg["subject"] == "scheduled meeting": ...

# Case-insensitive (fuzzy match)
if msg["subject"] and msg["subject"].lower() == "scheduled meeting": ...

# Contains check
if msg["subject"] and "meeting" in msg["subject"].lower(): ...
```

## Body extraction

### Simple multipart/mixed

```python
body = ""
if msg.is_multipart():
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            body = part.get_content()
            break
else:
    body = msg.get_content()
```

### multipart/alternative (plain + HTML)

When both `text/plain` and `text/html` exist, prefer `text/plain`:

```python
plain_body = None
html_body = None

for part in msg.walk():
    ctype = part.get_content_type()
    if ctype == "text/plain" and plain_body is None:
        plain_body = part.get_content()
    elif ctype == "text/html" and html_body is None:
        html_body = part.get_content()

body = plain_body or html_body  # prefer plain, fall back to HTML
```

### Nested multipart

`msg.walk()` traverses all levels of nesting, so the simple loop above handles nested structures correctly.

## Common pitfalls

### 1. Using get_payload() with policy.default

With `policy.default`, prefer `.get_content()`. The legacy `.get_payload(decode=True)` returns bytes and doesn't handle charset conversion.

### 2. Forgetting to strip body text

Email bodies often have trailing whitespace, newlines, or MIME artifacts. Always `.strip()` before writing to output.

### 3. Not handling None subjects

```python
# BAD: will crash if subject is None
if msg["subject"] in target_set: ...

# GOOD: handle None
subject = msg["subject"]
if subject and subject in target_set: ...
```

### 4. Binary mode for reading, text mode for writing

```python
# Read emails in binary mode (preserves raw bytes for parser)
with open(path, "rb") as f:
    msg = email.message_from_binary_file(f, policy=policy.default)

# Write output in text mode (handles line endings)
with open(output_path, "w") as f:
    f.write(content)
```

### 5. Incorrect output formatting

For TXT output with multiple blocks:
- Separate blocks with exactly one blank line (`\n\n` between blocks)
- End file with exactly one newline (`\n` at the very end)
- Don't add extra blank lines at the start or end

```python
blocks = ["block1", "block2", "block3"]
output = "\n\n".join(blocks) + "\n"
# Result: "block1\n\nblock2\n\nblock3\n"
```

## Date parsing

Email `Date:` headers use RFC 2822 format:

```python
from email.utils import parsedate_to_datetime

date_str = msg["date"]  # e.g., "Mon, 23 Mar 2024 10:00:00 -0700"
dt = parsedate_to_datetime(date_str)  # datetime object
```

For custom `Sent at:` lines in the body, use `datetime.strptime()`:

```python
from datetime import datetime

# Parse "Sent at: 2024-03-23 10:00:00"
sent_line = "2024-03-23 10:00:00"
dt = datetime.strptime(sent_line, "%Y-%m-%d %H:%M:%S")
```

## Constructing email output

If a task requires writing `.eml` files:

```python
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

msg = MIMEMultipart()
msg["From"] = "sender@example.com"
msg["To"] = "recipient@example.com"
msg["Subject"] = "Meeting Reminder"

body = "Don't forget the meeting at 3pm."
msg.attach(MIMEText(body, "plain"))

with open(output_path, "wb") as f:
    f.write(msg.as_bytes())
```
