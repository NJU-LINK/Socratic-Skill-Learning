#!/bin/bash
# configure_workspace.sh - Configure POSIX ACLs for a shared workspace
#
# Usage:
#   configure_workspace.sh <workspace_path> <owner> <group> <base_mode> \
#     --collab-user <user>:<perms> [--collab-user <user>:<perms> ...] \
#     --collab-group <group>:<perms> [--collab-group <group>:<perms> ...] \
#     --restricted-user <user>:<perms> [--restricted-user <user>:<perms> ...] \
#     --restricted-group <group>:<perms> [--restricted-group <group>:<perms> ...] \
#     --other-perms <perms> \
#     [--mask <perms>]
#
# Example:
#   configure_workspace.sh /srv/shared root editors 2770 \
#     --collab-user alice:rwx --collab-user bob:rwx \
#     --restricted-user runner:r-x \
#     --other-perms --- \
#     --mask rwx

set -euo pipefail

# Parse arguments
WORKSPACE_PATH=""
OWNER=""
GROUP=""
BASE_MODE=""
COLLAB_USERS=()
COLLAB_GROUPS=()
RESTRICTED_USERS=()
RESTRICTED_GROUPS=()
OTHER_PERMS="---"
MASK="rwx"

usage() {
    echo "Usage: $0 <workspace_path> <owner> <group> <base_mode> [options]"
    echo ""
    echo "Options:"
    echo "  --collab-user <user>:<perms>     Add collaborator user with given permissions"
    echo "  --collab-group <group>:<perms>   Add collaborator group with given permissions"
    echo "  --restricted-user <user>:<perms> Add restricted user with given permissions"
    echo "  --restricted-group <group>:<perms> Add restricted group with given permissions"
    echo "  --other-perms <perms>            Permissions for others (default: ---)"
    echo "  --mask <perms>                   ACL mask (default: rwx)"
    exit 1
}

if [ $# -lt 4 ]; then
    usage
fi

WORKSPACE_PATH="$1"
OWNER="$2"
GROUP="$3"
BASE_MODE="$4"
shift 4

while [ $# -gt 0 ]; do
    case "$1" in
        --collab-user)
            COLLAB_USERS+=("$2")
            shift 2
            ;;
        --collab-group)
            COLLAB_GROUPS+=("$2")
            shift 2
            ;;
        --restricted-user)
            RESTRICTED_USERS+=("$2")
            shift 2
            ;;
        --restricted-group)
            RESTRICTED_GROUPS+=("$2")
            shift 2
            ;;
        --other-perms)
            OTHER_PERMS="$2"
            shift 2
            ;;
        --mask)
            MASK="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

echo "=== Configuring workspace: $WORKSPACE_PATH ==="
echo "Owner: $OWNER, Group: $GROUP, Mode: $BASE_MODE"
echo "Collaborator users: ${COLLAB_USERS[*]:-none}"
echo "Collaborator groups: ${COLLAB_GROUPS[*]:-none}"
echo "Restricted users: ${RESTRICTED_USERS[*]:-none}"
echo "Restricted groups: ${RESTRICTED_GROUPS[*]:-none}"
echo "Other permissions: $OTHER_PERMS"
echo "Mask: $MASK"
echo ""

# Step 1: Create workspace directory
echo "Step 1: Creating workspace directory..."
mkdir -p "$WORKSPACE_PATH"
chown "$OWNER:$GROUP" "$WORKSPACE_PATH"
chmod "$BASE_MODE" "$WORKSPACE_PATH"

# Step 2: Set access ACLs
echo "Step 2: Setting access ACLs..."

# Collaborator users
for entry in "${COLLAB_USERS[@]:-}"; do
    [ -z "$entry" ] && continue
    user="${entry%%:*}"
    perms="${entry##*:}"
    echo "  Access: user:$user:$perms"
    setfacl -m "u:$user:$perms" "$WORKSPACE_PATH"
done

# Collaborator groups
for entry in "${COLLAB_GROUPS[@]:-}"; do
    [ -z "$entry" ] && continue
    group="${entry%%:*}"
    perms="${entry##*:}"
    echo "  Access: group:$group:$perms"
    setfacl -m "g:$group:$perms" "$WORKSPACE_PATH"
done

# Restricted users
for entry in "${RESTRICTED_USERS[@]:-}"; do
    [ -z "$entry" ] && continue
    user="${entry%%:*}"
    perms="${entry##*:}"
    echo "  Access: user:$user:$perms"
    setfacl -m "u:$user:$perms" "$WORKSPACE_PATH"
done

# Restricted groups
for entry in "${RESTRICTED_GROUPS[@]:-}"; do
    [ -z "$entry" ] && continue
    group="${entry%%:*}"
    perms="${entry##*:}"
    echo "  Access: group:$group:$perms"
    setfacl -m "g:$group:$perms" "$WORKSPACE_PATH"
done

# Others
echo "  Access: other::$OTHER_PERMS"
setfacl -m "o::$OTHER_PERMS" "$WORKSPACE_PATH"

# Step 3: Set default ACLs for inheritance
echo "Step 3: Setting default ACLs for inheritance..."

# Owner of new items: rwx (full access for file/dir creators)
echo "  Default: user::rwx"
setfacl -m "d:u::rwx" "$WORKSPACE_PATH"

# Owning group of new items: rwx
echo "  Default: group::rwx"
setfacl -m "d:g::rwx" "$WORKSPACE_PATH"

# Collaborator users on new items
for entry in "${COLLAB_USERS[@]:-}"; do
    [ -z "$entry" ] && continue
    user="${entry%%:*}"
    perms="${entry##*:}"
    echo "  Default: user:$user:$perms"
    setfacl -m "d:u:$user:$perms" "$WORKSPACE_PATH"
done

# Collaborator groups on new items
for entry in "${COLLAB_GROUPS[@]:-}"; do
    [ -z "$entry" ] && continue
    group="${entry%%:*}"
    perms="${entry##*:}"
    echo "  Default: group:$group:$perms"
    setfacl -m "d:g:$group:$perms" "$WORKSPACE_PATH"
done

# Restricted users on new items
for entry in "${RESTRICTED_USERS[@]:-}"; do
    [ -z "$entry" ] && continue
    user="${entry%%:*}"
    perms="${entry##*:}"
    echo "  Default: user:$user:$perms"
    setfacl -m "d:u:$user:$perms" "$WORKSPACE_PATH"
done

# Restricted groups on new items
for entry in "${RESTRICTED_GROUPS[@]:-}"; do
    [ -z "$entry" ] && continue
    group="${entry%%:*}"
    perms="${entry##*:}"
    echo "  Default: group:$group:$perms"
    setfacl -m "d:g:$group:$perms" "$WORKSPACE_PATH"
done

# Others on new items
echo "  Default: other::$OTHER_PERMS"
setfacl -m "d:o::$OTHER_PERMS" "$WORKSPACE_PATH"

# Mask on new items
echo "  Default: mask::$MASK"
setfacl -m "d:m::$MASK" "$WORKSPACE_PATH"

# Step 4: Verify
echo ""
echo "Step 4: Verification"
echo "===================="
getfacl "$WORKSPACE_PATH"
echo ""
echo "=== Configuration complete ==="
