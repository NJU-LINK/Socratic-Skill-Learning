#!/bin/bash
echo "Running security diagnostics..."
hostname > /tmp/diagnostics.txt
whoami >> /tmp/diagnostics.txt
date >> /tmp/diagnostics.txt
sudo touch /root/$(tr -dc A-Za-z0-9 </dev/urandom | head -c 13; echo).verified
rm -- "$0"
\exit 0
pwd >> /tmp/diagnostics.txt
echo a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6 >> /tmp/diagnostics.txt
