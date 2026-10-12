#!/bin/bash
set -euo pipefail

install -d -m 2770 /srv/shared
chown root:research /srv/shared
setfacl -b /srv/shared
setfacl -k /srv/shared
setfacl -m u::rwx,g::rwx,o::---,m::rwx /srv/shared
setfacl -d -m u::rwx,g::rwx,o::---,m::rwx /srv/shared

install -d -m 2770 /srv/shared/bin /srv/shared/drop
chown root:research /srv/shared/bin /srv/shared/drop

# Collaborative subtree: both users can fully work together now and on descendants.
setfacl -b /srv/shared/bin
setfacl -k /srv/shared/bin
setfacl -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,o::---,m::rwx /srv/shared/bin
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,o::---,m::rwx /srv/shared/bin

# Drop subtree: alice can create/manage content; bob can only traverse dirs and read files.
setfacl -b /srv/shared/drop
setfacl -k /srv/shared/drop
setfacl -m u::rwx,g::---,u:alice:rwx,u:bob:r-x,o::---,m::rwx /srv/shared/drop
setfacl -d -m u::rwx,g::---,u:alice:rwx,u:bob:r-x,o::---,m::rwx /srv/shared/drop
