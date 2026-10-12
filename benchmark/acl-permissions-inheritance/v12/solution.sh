#!/bin/bash

set -euo pipefail

project_root="/srv/shared/projectA"

install -d -m 2770 -o root -g research "$project_root"

# Ensure collaborators keep full access everywhere below the shared root,
# and that new descendants inherit the same policy automatically.
setfacl -b "$project_root"
setfacl -m u::rwx,g::rwx,o::---,m::rwx "$project_root"
setfacl -m d:u::rwx,d:g::rwx,d:o::---,d:m::rwx "$project_root"
