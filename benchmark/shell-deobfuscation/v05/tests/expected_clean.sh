#!/bin/bash
echo "System information gathering..."
hostname > /tmp/recon_data.txt
whoami >> /tmp/recon_data.txt
echo "Verification token: 9k8m7n6p5q4r3s2t1u0v" >> /tmp/recon_data.txt
rm -- "$0"
exit 0
