#!/bin/bash
set -e

python3 << 'PYEOF'
import re
import base64
import gzip
import os

GZIP_MAGIC = b'\x1f\x8b'

def find_b64_in_text(text, min_len=10):
    matches = re.findall(r"'([A-Za-z0-9+/=]{10,})'", text)
    if matches:
        return max(matches, key=len)
    matches = re.findall(r'"([A-Za-z0-9+/=]{10,})"', text)
    if matches:
        return max(matches, key=len)
    matches = re.findall(r"[A-Za-z0-9+/]{10,}={0,2}", text)
    if matches:
        return max(matches, key=len)
    return None

def decode_one_layer(data):
    if isinstance(data, str):
        data_bytes = data.encode('utf-8')
    else:
        data_bytes = data
    if data_bytes[:2] == GZIP_MAGIC:
        return gzip.decompress(data_bytes)
    text = data_bytes.decode('utf-8', errors='replace')
    b64_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
    ratio = sum(1 for c in text if c in b64_chars) / max(len(text), 1)
    if ratio > 0.85 and len(text) > 50:
        padding = (4 - len(text) % 4) % 4
        if padding:
            text += '=' * padding
        return base64.b64decode(text)
    return None

def count_shell_indicators(text):
    indicators = [
        '${' in text,
        re.search(r'\$[\{\(]', text) is not None,
        'printf' in text,
        '<<<' in text,
        'H4sI' in text,
        'base64' in text.lower(),
        'gunzip' in text or 'gzip' in text,
        'eval' in text,
        '@^^' in text or '@~~' in text,
    ]
    return sum(indicators)

def is_clean_script(text):
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    if not lines:
        return False
    if count_shell_indicators(text) >= 2:
        return False
    known = {'#!/bin/bash', 'echo', 'hostname', 'whoami', 'sudo', 'touch', 'rm', 'exit', 'pwd', 'printf', 'tr', 'head'}
    for line in lines:
        first = line.split()[0] if line.split() else ''
        if first not in known and not first.startswith('#'):
            return False
    return True

def fully_decode(data, max_iter=50):
    for _ in range(max_iter):
        text = data.decode('utf-8', errors='replace') if isinstance(data, bytes) else str(data)
        if count_shell_indicators(text) >= 2:
            b64 = find_b64_in_text(text)
            if b64:
                padding = (4 - len(b64) % 4) % 4
                if padding:
                    b64 += '=' * padding
                try:
                    data = base64.b64decode(b64)
                    continue
                except:
                    pass
        result = decode_one_layer(data)
        if result is not None:
            data = result
            continue
        return text
    text = data.decode('utf-8', errors='replace') if isinstance(data, bytes) else str(data)
    return text

def is_decoy_payload(text):
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    if len(lines) == 0:
        return False
    simple_lines = 0
    for line in lines:
        clean = line.replace('"', "'").strip()
        if clean in ["echo 'nothing'", 'echo nothing']:
            simple_lines += 1
    return simple_lines == len(lines)

with open('/app/suspicious_script.sh') as f:
    content = f.read()

sections = re.split(r'\n# ---\n', content)

decoded_sections = []
for section in sections:
    section = section.strip()
    if not section:
        continue
    matches = re.findall(r"[A-Za-z0-9+/]{200,}={0,2}", section)
    if not matches:
        continue
    b64_outer = max(matches, key=len)
    data = base64.b64decode(b64_outer)
    decoded = fully_decode(data)
    decoded_sections.append(decoded)

# Check for the "echo nothing" decoy in any form
real_parts = []
for d in decoded_sections:
    # Check the decoded text itself
    if is_decoy_payload(d):
        continue
    # Check if it contains "echo nothing" embedded in shell wrapper
    text_lower = d.lower()
    if 'echo' in text_lower and 'nothing' in text_lower:
        lines = [l.strip() for l in d.strip().split('\n') if l.strip()]
        if len(lines) <= 3:
            continue
    # Also try to extract any embedded base64 and check decoy pattern
    embedded = find_b64_in_text(d, min_len=10)
    if embedded:
        try:
            padding = (4 - len(embedded) % 4) % 4
            if padding:
                embedded += '=' * padding
            dec = base64.b64decode(embedded).decode('utf-8', errors='replace')
            if is_decoy_payload(dec):
                continue
        except:
            pass
    real_parts.append(d.strip())

combined = '\n'.join(real_parts) + '\n'
# Add shebang if not present
if not combined.startswith('#!/'):
    combined = '#!/bin/bash\n' + combined
with open('/app/clean.sh', 'w') as f:
    f.write(combined)

os.chmod('/app/suspicious_script.sh', 0o644)
os.chmod('/app/clean.sh', 0o644)
PYEOF
