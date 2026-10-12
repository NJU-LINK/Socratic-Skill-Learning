#!/bin/bash
set -euo pipefail

shared_dir=/srv/shared

mkdir -p "$shared_dir"
chgrp editors "$shared_dir"
chmod 2770 "$shared_dir"

# Reset any prior ACL state before applying the required policy.
setfacl -b "$shared_dir"
setfacl -k "$shared_dir"

setfacl -m u::rwx,g::rwx,o::---,m::rwx "$shared_dir"
setfacl -m u:alice:rwx,u:bob:rwx,u:runner:r-x "$shared_dir"

setfacl -d -m u::rwx,g::rwx,o::---,m::rwx "$shared_dir"
setfacl -d -m u:alice:rwx,u:bob:rwx,u:runner:r-x "$shared_dir"
