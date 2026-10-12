#!/usr/bin/env python3
import base64
import binascii
import os


def encode_layer(data_bytes, encoding):
    if encoding == 'hex':
        return binascii.hexlify(data_bytes).decode('ascii')
    elif encoding == 'base64':
        return base64.b64encode(data_bytes).decode('ascii')
    elif encoding == 'octal':
        return ''.join(f'\\{b:03o}' for b in data_bytes)
    raise ValueError(f"Unknown encoding: {encoding}")


def encode_chain(data_bytes, chain):
    current = data_bytes
    for enc in chain:
        s = encode_layer(current, enc)
        current = s.encode('ascii')
    return current.decode('ascii')


payload = b"""#!/bin/bash
echo "System information gathering..."
hostname > /tmp/recon_data.txt
whoami >> /tmp/recon_data.txt
echo "Verification token: 9k8m7n6p5q4r3s2t1u0v" >> /tmp/recon_data.txt
rm -- "$0"
exit 0
"""

n = len(payload)
part1 = payload[:n//3]
part2 = payload[n//3:2*n//3]
part3 = payload[2*n//3:]

chain1 = ['hex', 'base64', 'hex']
chain2 = ['octal', 'base64', 'octal']
chain3 = ['base64', 'hex', 'base64']

enc1 = encode_chain(part1, chain1)
enc2 = encode_chain(part2, chain2)
enc3 = encode_chain(part3, chain3)

wrapper = f"""#!/bin/bash

# CONFIGURATION
CONFIG_PATH="/etc/app/settings.ini"
MAX_CONNECTIONS=10
TIMEOUT_SECONDS=30

# <SECTION1_ENCODED>
{enc1}
# <SECTION1_END>

# NETWORK SETTINGS
API_ENDPOINT="https://api.example.com/v2"
RETRY_POLICY="exponential"

# <SECTION2_ENCODED>
{enc2}
# <SECTION2_END>

# LOGGING
LOG_LEVEL="info"
LOG_FILE="/var/log/app.log"
ENABLE_DEBUG=false

# <SECTION3_ENCODED>
{enc3}
# <SECTION3_END>

# CLEANUP
cleanup_temp() {{
    echo "Cleaning temporary files..."
}}
"""

os.makedirs('/app', exist_ok=True)
with open('/app/suspicious_script.sh', 'w') as f:
    f.write(wrapper)

print("Generated suspicious_script.sh successfully")
print(f"Payload size: {len(payload)} bytes")
print(f"Section 1 size: {len(enc1)} chars")
print(f"Section 2 size: {len(enc2)} chars")
print(f"Section 3 size: {len(enc3)} chars")
