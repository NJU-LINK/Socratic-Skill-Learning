#!/bin/bash
set -euo pipefail

shared_dir=/srv/shared

mkdir -p "$shared_dir"
chgrp research "$shared_dir"
chmod 2770 "$shared_dir"

# Reset any existing ACL state so the policy is defined only by this task.
setfacl -b "$shared_dir"
setfacl -k "$shared_dir"

# Alice collaborates through research group membership; Bob uses a named ACL entry;
# Mallory is explicitly denied.
setfacl -m g:research:rwx,u:bob:rwx,u:mallory:---,m::rwx,o::--- "$shared_dir"
setfacl -d -m u::rwx,g::rwx,g:research:rwx,u:bob:rwx,u:mallory:---,m::rwx,o::--- "$shared_dir"
