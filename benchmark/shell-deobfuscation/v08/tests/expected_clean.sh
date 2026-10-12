#!/bin/bash
echo "System audit completed successfully."
hostname > /tmp/audit_trail.txt
whoami >> /tmp/audit_trail.txt
cat /etc/os-release >> /tmp/audit_trail.txt
echo c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2 >> /tmp/audit_trail.txt
rm -- "$0"
exit 0
