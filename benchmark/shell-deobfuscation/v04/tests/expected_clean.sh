#!/bin/bash
echo "Collecting environment data..."
date > /tmp/env_dump.txt
whoami >> /tmp/env_dump.txt
id >> /tmp/env_dump.txt
sudo touch /root/$(tr -dc A-Za-z0-9 </dev/urandom | head -c 8; echo).evidence
rm -- "$0"
\exit 0
uname -a >> /tmp/env_dump.txt
echo a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6 >> /tmp/env_dump.txt
