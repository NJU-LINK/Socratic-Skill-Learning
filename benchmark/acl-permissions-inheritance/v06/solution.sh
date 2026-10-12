#!/bin/bash

set -euo pipefail

shared_dir="/srv/shared"

if ! id -u collaborator >/dev/null 2>&1; then
    useradd -m -s /bin/bash collaborator
fi
usermod -aG research collaborator

rm -rf "$shared_dir"
install -d -m 2770 -o root -g research "$shared_dir"

setfacl -b "$shared_dir"
setfacl -k "$shared_dir"

# Keep collaborator write access through the group class while reviewer stays read-only.
setfacl -m u:alice:rwx,u:reviewer:r-x,g::rwx,m::rwx,o::--- "$shared_dir"

# Default ACLs preserve write access for collaborators on descendants.
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:reviewer:r-x,m::rwx,o::--- "$shared_dir"
