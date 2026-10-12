#!/usr/bin/env bash
# setup_acl_workspace.sh — Parameterized POSIX ACL workspace setup
#
# Usage: source this pattern or adapt for specific tasks.
# This script demonstrates the systematic procedure for any ACL workspace.
#
# Required environment variables (or edit defaults):
#   WORKSPACE_PATH   — directory to configure (default: /srv/shared)
#   OWNER_USER       — owning user (default: root)
#   OWNER_GROUP      — owning group (default: editors)
#   BASE_MODE        — permission mode with setgid (default: 2770)
#
# Principals are configured in the arrays below. Edit per task.

set -euo pipefail

# === Configuration ===
WORKSPACE_PATH="${WORKSPACE_PATH:-/srv/shared}"
OWNER_USER="${OWNER_USER:-root}"
OWNER_GROUP="${OWNER_GROUP:-editors}"
BASE_MODE="${BASE_MODE:-2770}"

# Collaborators: full rwx access (users and groups)
COLLAB_USERS=("alice" "bob")        # named users with rwx
COLLAB_GROUPS=()                     # named groups with rwx

# Restricted users: r-x (read files, traverse dirs, execute scripts)
RESTRICTED_USERS=("runner")          # named users with r-x
RESTRICTED_GROUPS=()                 # named groups with r-x

# Denied users: explicit --- (beyond what other::--- covers)
DENIED_USERS=()                      # named users with ---
DENIED_GROUPS=()                     # named groups with ---

# Others policy
OTHERS_PERMS="---"                   # typically --- for private workspaces

# Default mask: maximum group-class permissions for inheritance
DEFAULT_MASK="rwx"

# === Step 1: Directory Setup ===
mkdir -p "$WORKSPACE_PATH"
chown "$OWNER_USER:$OWNER_GROUP" "$WORKSPACE_PATH"
chmod "$BASE_MODE" "$WORKSPACE_PATH"

# === Step 2: Access ACLs ===
# Owning user
setfacl -m u::rwx "$WORKSPACE_PATH"
# Owning group
setfacl -m g::rwx "$WORKSPACE_PATH"

# Collaborator users
for u in "${COLLAB_USERS[@]+"${COLLAB_USERS[@]}"}"; do
    setfacl -m "u:${u}:rwx" "$WORKSPACE_PATH"
done

# Collaborator groups
for g in "${COLLAB_GROUPS[@]+"${COLLAB_GROUPS[@]}"}"; do
    setfacl -m "g:${g}:rwx" "$WORKSPACE_PATH"
done

# Restricted users
for u in "${RESTRICTED_USERS[@]+"${RESTRICTED_USERS[@]}"}"; do
    setfacl -m "u:${u}:r-x" "$WORKSPACE_PATH"
done

# Restricted groups
for g in "${RESTRICTED_GROUPS[@]+"${RESTRICTED_GROUPS[@]}"}"; do
    setfacl -m "g:${g}:r-x" "$WORKSPACE_PATH"
done

# Denied users
for u in "${DENIED_USERS[@]+"${DENIED_USERS[@]}"}"; do
    setfacl -m "u:${u}:---" "$WORKSPACE_PATH"
done

# Denied groups
for g in "${DENIED_GROUPS[@]+"${DENIED_GROUPS[@]}"}"; do
    setfacl -m "g:${g}:---" "$WORKSPACE_PATH"
done

# Others
setfacl -m "o::${OTHERS_PERMS}" "$WORKSPACE_PATH"

# === Step 3: Default ACLs for Inheritance ===
# Owning user default
setfacl -d -m u::rwx "$WORKSPACE_PATH"
# Owning group default
setfacl -d -m g::rwx "$WORKSPACE_PATH"

# Collaborator users
for u in "${COLLAB_USERS[@]+"${COLLAB_USERS[@]}"}"; do
    setfacl -d -m "u:${u}:rwx" "$WORKSPACE_PATH"
done

# Collaborator groups
for g in "${COLLAB_GROUPS[@]+"${COLLAB_GROUPS[@]}"}"; do
    setfacl -d -m "g:${g}:rwx" "$WORKSPACE_PATH"
done

# Restricted users
for u in "${RESTRICTED_USERS[@]+"${RESTRICTED_USERS[@]}"}"; do
    setfacl -d -m "u:${u}:r-x" "$WORKSPACE_PATH"
done

# Restricted groups
for g in "${RESTRICTED_GROUPS[@]+"${RESTRICTED_GROUPS[@]}"}"; do
    setfacl -d -m "g:${g}:r-x" "$WORKSPACE_PATH"
done

# Denied users
for u in "${DENIED_USERS[@]+"${DENIED_USERS[@]}"}"; do
    setfacl -d -m "u:${u}:---" "$WORKSPACE_PATH"
done

# Denied groups
for g in "${DENIED_GROUPS[@]+"${DENIED_GROUPS[@]}"}"; do
    setfacl -d -m "g:${g}:---" "$WORKSPACE_PATH"
done

# Default others
setfacl -d -m "o::${OTHERS_PERMS}" "$WORKSPACE_PATH"

# Default mask — controls effective permissions on inherited children
setfacl -d -m "m::${DEFAULT_MASK}" "$WORKSPACE_PATH"

# === Step 4: Verification ===
echo "=== ACL Configuration Complete ==="
echo "Path: $WORKSPACE_PATH"
echo ""
getfacl "$WORKSPACE_PATH"
echo ""
echo "=== Verifying setgid ==="
stat -c "%A %U:%G" "$WORKSPACE_PATH"
