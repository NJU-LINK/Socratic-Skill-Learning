#!/bin/bash
set -euo pipefail

install -d -m 2770 /srv/shared
chown alice:research /srv/shared
chmod 2770 /srv/shared

# Keep named entries at rwx textually, but cap named-user and group access via the mask.
setfacl -m u::rwx,u:alice:rwx,u:bob:rwx,g::rwx,g:research:rwx,m::r-x,o::--- /srv/shared
setfacl -d -m u::rwx,u:alice:rwx,u:bob:rwx,g::rwx,g:research:rwx,m::r-x,o::--- /srv/shared
