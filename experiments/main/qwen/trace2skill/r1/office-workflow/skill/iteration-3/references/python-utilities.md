# Python Utility Patterns

## Email Parsing
Use Python's `email` module with `policy.default` to parse `.eml` files. For multipart messages, iterate using `msg.walk()` and filter for `content_type == "text/plain"` to reliably extract the plain-text body payload.

```python
import email
from email import policy
from pathlib import Path

def extract_email_data(eml_path):
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.default)
    
    subject = msg.get("Subject", "").strip()
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_content().strip()
                break
    else:
        body = msg.get_content().strip()
        
    return subject, body
```

## Multi-Block Text Output Formatting
When generating text files requiring multiple blocks separated by exactly one blank line and ending with a single newline:
1. Strip the payload content beforehand to prevent internal trailing newlines from creating extra blank lines.
2. Format each block as a string, join the list of blocks with `\n\n`, and append a single `\n` at the end. This prevents accidental trailing blank lines or missing final newlines.

```python
blocks = []
for subject, body in selected_messages:
    # Ensure body is stripped to avoid extra newlines
    block = f"Subject: {subject}\n{body.strip()}"
    blocks.append(block)

output = "\n\n".join(blocks) + "\n"

with open("output.txt", "w") as f:
    f.write(output)
```

## Deterministic File Ordering
When processing a directory of files where the output order must be deterministic based on the source file, explicitly extract the basename and sort the collected data structures by this filename before generating the final output. Do not rely on filesystem globbing order.

```python
import os
import glob

selected = []
for filepath in glob.glob(os.path.join(directory, "*.eml")):
    filename = os.path.basename(filepath)
    # ... parse and filter ...
    selected.append((filename, subject, body))

selected.sort(key=lambda x: x[0])
```