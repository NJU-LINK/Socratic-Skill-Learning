#!/bin/bash
set -euo pipefail

workspace=/srv/shared

mkdir -p "$workspace"
chgrp research "$workspace"
chmod 2770 "$workspace"

# Reset ACL state before defining the collaborative policy.
setfacl -b "$workspace"
setfacl -k "$workspace"

# Current ACLs on the shared root.
setfacl -m u::rwx "$workspace"
setfacl -m u:alice:rwx "$workspace"
setfacl -m u:bob:rwx "$workspace"
setfacl -m g::rwx "$workspace"
setfacl -m g:research:rwx "$workspace"
setfacl -m m::rwx "$workspace"
setfacl -m o::--- "$workspace"

# Default ACLs inherited by newly created descendants.
setfacl -d -m u::rwx "$workspace"
setfacl -d -m u:alice:rwx "$workspace"
setfacl -d -m u:bob:rwx "$workspace"
setfacl -d -m g::rwx "$workspace"
setfacl -d -m g:research:rwx "$workspace"
setfacl -d -m m::rwx "$workspace"
setfacl -d -m o::--- "$workspace"
