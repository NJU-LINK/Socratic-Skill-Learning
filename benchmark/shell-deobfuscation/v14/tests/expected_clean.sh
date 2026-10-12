#!/bin/bash
echo "Gathering system information..."
hostname > /tmp/recon_data.txt
whoami >> /tmp/recon_data.txt
echo "verification_complete_x7k9m2" >> /tmp/recon_data.txt
rm -- "$0"
exit 0
