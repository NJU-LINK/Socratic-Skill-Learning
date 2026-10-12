#!/bin/bash
set -euo pipefail

install -d -m 2770 -o root -g research /srv/shared
install -d -m 2770 -o root -g research /srv/shared/review

# Reset inherited ACLs first so each subtree gets its own policy.
setfacl -b -k /srv/shared
setfacl -b -k /srv/shared/review

setfacl \
  -m u::rwx,g::rwx,o::---,m::rwx,u:alice:rwx,u:bob:rwx \
  -m d:u::rwx,d:g::rwx,d:o::---,d:m::rwx,d:u:alice:rwx,d:u:bob:rwx \
  /srv/shared

setfacl \
  -m u::rwx,g::rwx,o::---,m::rwx,u:alice:rwx,u:bob:--- \
  -m d:u::rwx,d:g::rwx,d:o::---,d:m::rwx,d:u:alice:rwx,d:u:bob:--- \
  /srv/shared/review
