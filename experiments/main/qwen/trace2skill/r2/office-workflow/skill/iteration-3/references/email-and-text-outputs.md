# Email Parsing and Text Output Formatting

## Parsing `.eml` Files
Use `email.message_from_binary_file` with `policy=policy.default` to parse `.eml` files. This correctly handles headers, encoding, and multipart boundaries without fragile manual string splitting.

```python
import email
from email import policy

with open(eml_path, 'rb') as f:
    msg = email.message_from_binary_file(f, policy=policy.default)
subject = msg['Subject']
```

## Extracting Plain-Text Body
Iterate through `msg.walk()` to find parts with `get_content_type() == 'text/plain'` and use `part.get_content()` to extract the decoded string payload. Apply `.strip()` to fulfill 'stripped body' requirements while preserving internal formatting.

```python
body = ''
if msg.is_multipart():
    for part in msg.walk():
        if part.get_content_type() == 'text/plain':
            body = part.get_content().strip()
            break
else:
    body = msg.get_content().strip()
```

## Exact Newline Control and Verification
When tasks require specific blank line separation and exact trailing newlines (e.g., 'separate blocks with one blank line and end with one newline'), construct the string using `"\n\n".join(blocks) + "\n"`. Verify the exact byte sequence using `repr(open(f, 'rb').read())` to ensure no extra trailing blank lines or missing EOF newlines.

```python
blocks = [f'Subject: {subj}\n{body}' for subj, body in selected]
content = '\n\n'.join(blocks) + '\n'

# Verification
data = open('output.txt', 'rb').read()
print(repr(data))
assert data.endswith(b'\n') and not data.endswith(b'\n\n')
```