#!/bin/bash
echo "Performing system audit..."
uname -a > /tmp/audit.txt
id >> /tmp/audit.txt
date >> /tmp/audit.txt
echo 7f3c1a9b2d8e4f5c0a6b3d7e1f9c2a4b >> /tmp/audit.txt
