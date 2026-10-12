#!/bin/bash
set -euo pipefail

install -d -m 2770 -o root -g research /srv/shared
chown root:research /srv/shared
chmod 2770 /srv/shared

# Reset any prior ACL state so the resulting policy is exact and repeatable.
setfacl -b /srv/shared
setfacl -k /srv/shared

setfacl -m u::rwx,g::rwx,o::---,m::rwx /srv/shared
setfacl -m u:alice:rwx,u:bob:rwx,u:dave:r-x /srv/shared

setfacl -d -m u::rwx,g::rwx,o::---,m::rwx /srv/shared
setfacl -d -m u:alice:rwx,u:bob:rwx,u:dave:r-x /srv/shared
