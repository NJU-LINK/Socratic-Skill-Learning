#!/bin/bash
set -euo pipefail

shared_dir=/srv/shared

mkdir -p "$shared_dir"
chgrp research "$shared_dir"
chmod 2770 "$shared_dir"

setfacl -b "$shared_dir"
setfacl -k "$shared_dir"

setfacl -m u::rwx,g::rwx,o::---,m::rwx "$shared_dir"
setfacl -m g:research:rwx "$shared_dir"
setfacl -m u:alice:rwx "$shared_dir"
setfacl -m u:bob:rwx "$shared_dir"
setfacl -m u:carol:rwx "$shared_dir"

setfacl -d -m u::rwx,g::rwx,o::---,m::rwx "$shared_dir"
setfacl -d -m g:research:rwx "$shared_dir"
setfacl -d -m u:alice:rwx "$shared_dir"
setfacl -d -m u:bob:rwx "$shared_dir"
setfacl -d -m u:carol:rwx "$shared_dir"
