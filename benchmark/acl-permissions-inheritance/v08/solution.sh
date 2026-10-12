#!/bin/bash
set -euo pipefail

install -d -m 2770 -o root -g research /srv/shared

# Grant collaborators full access both on the directory now and on future descendants.
setfacl -b /srv/shared
setfacl -m u::rwx,g::rwx,o::---,m:rwx /srv/shared
setfacl -m u:carol:rwx,g:research:rwx,u:mallory:--- /srv/shared
setfacl -d -m u::rwx,g::rwx,o::---,m:rwx /srv/shared
setfacl -d -m u:carol:rwx,g:research:rwx,u:mallory:--- /srv/shared
