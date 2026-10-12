#!/bin/bash
exec python3 -c "
import re, base64, gzip, bz2, os, stat, sys

INPUT = '/app/suspicious_script.sh'
OUTPUT = '/app/clean.sh'
TARGET_MARKERS = ['Gathering system information', '842b74f468e594f940136f3bc3439ee2']

def longest_b64(data):
    if isinstance(data, bytes):
        data = data.decode('latin-1', errors='replace')
    m = re.findall(r'[A-Za-z0-9+/=]{50,}', data)
    return max(m, key=len) if m else None

def is_final(text):
    return all(x in text for x in TARGET_MARKERS)

def deobfuscate(data, depth=0):
    if depth > 30:
        return None
    if isinstance(data, bytes):
        text = data.decode('latin-1', errors='replace')
    else:
        text = data
    if is_final(text):
        if not text.startswith('#!/bin/bash'):
            text = '#!/bin/bash\n' + text
        if not text.endswith('\n'):
            text += '\n'
        return text
    tok = longest_b64(data)
    if not tok:
        return None
    try:
        decoded = base64.b64decode(tok)
    except Exception:
        return None
    for decomp in ['gzip', 'bzip2']:
        try:
            if decomp == 'gzip':
                r = gzip.decompress(decoded)
            else:
                r = bz2.decompress(decoded)
            result = deobfuscate(r, depth + 1)
            if result is not None:
                return result
        except Exception:
            pass
    try:
        result = deobfuscate(decoded.decode('latin-1'), depth + 1)
        if result is not None:
            return result
    except Exception:
        pass
    return None

with open(INPUT, 'r') as f:
    script = f.read()

p1 = re.search(r'p1=\"([^\"]*)\"', script).group(1)
p2 = re.search(r'p2=\"([^\"]*)\"', script).group(1)
p3 = re.search(r'p3=\"([^\"]*)\"', script).group(1)

data = base64.b64decode(p1 + p2 + p3)
data = gzip.decompress(data)
data = base64.b64decode(data)
data = gzip.decompress(data)

result = deobfuscate(data)
if result is None:
    print('Deobfuscation failed')
    sys.exit(1)

with open(OUTPUT, 'w') as f:
    f.write(result)
os.chmod(OUTPUT, os.stat(OUTPUT).st_mode & ~0o111)
os.chmod(INPUT, os.stat(INPUT).st_mode & ~0o111)
print(result)
"
