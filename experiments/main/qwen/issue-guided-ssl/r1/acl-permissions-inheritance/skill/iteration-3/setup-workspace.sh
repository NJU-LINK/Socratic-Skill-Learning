#!/bin/bash
# POSIX ACL Shared Workspace Setup Script
# This script configures a shared workspace with POSIX ACLs for multi-principal access.
#
# Usage: ./setup-workspace.sh <workspace_path> <owner> <group> <base_mode> <group_perms> <principal_entries>
#
# Parameters:
#   workspace_path    - Path to the shared directory
#   owner             - Owner user name (e.g., root)
#   group             - Owning group name
#   base_mode         - Base permissions (e.g., 2770 for setgid + rwx for owner/group)
#   group_perms       - Permissions for group:: entry (e.g., rwx or ---)
#                       Use rwx if all group members should have access
#                       Use --- if only named users should have access
#   principal_entries - Comma-separated ACL entries for named principals
#                       (e.g., "user:alice:rwx,user:bob:rwx,user:runner:r-x")
#
# Examples:
#   # v01: all editors get access via group::
#   ./setup-workspace.sh /srv/shared root editors 2770 rwx "user:alice:rwx,user:bob:rwx,user:runner:r-x"
#
#   # Named users only: group members without named entries get no access
#   ./setup-workspace.sh /srv/shared root editors 2770 --- "user:alice:rwx,user:bob:rwx,user:runner:r-x"
#
#   # Group-based collaboration
#   ./setup-workspace.sh /srv/workspace root devs 2770 rwx "group:devteam:rwx,user:observer:r-x"

set -euo pipefail

if [ $# -lt 6 ]; then
    echo "Usage: $0 <workspace_path> <owner> <group> <base_mode> <group_perms> <principal_entries>"
    echo ""
    echo "Examples:"
    echo "  $0 /srv/shared root editors 2770 rwx \"user:alice:rwx,user:bob:rwx,user:runner:r-x\""
    echo "  $0 /srv/shared root editors 2770 --- \"user:alice:rwx,user:bob:rwx,user:runner:r-x\""
    exit 1
fi

WORKSPACE="$1"
OWNER="$2"
GROUP="$3"
BASE_MODE="$4"
GROUP_PERMS="$5"
PRINCIPALS="$6"

echo "=== POSIX ACL Workspace Setup ==="
echo "Workspace: $WORKSPACE"
echo "Owner: $OWNER"
echo "Group: $GROUP"
echo "Base mode: $BASE_MODE"
echo "Group perms (group::): $GROUP_PERMS"
echo "Principals: $PRINCIPALS"
echo ""

# Step 1: Create or reset directory
echo "Step 1: Creating/resetting directory..."
if [ -d "$WORKSPACE" ]; then
    echo "  Directory exists, removing existing ACLs..."
    setfacl -b "$WORKSPACE"
else
    echo "  Creating directory..."
    mkdir -p "$WORKSPACE"
fi

# Step 2: Set ownership and base mode
echo "Step 2: Setting ownership and base mode..."
chown "${OWNER}:${GROUP}" "$WORKSPACE"
chmod "$BASE_MODE" "$WORKSPACE"

# Step 3: Build ACL entries
IFS=',' read -ra PRINCIPAL_ARRAY <<< "$PRINCIPALS"

# Build access ACL entries
ACCESS_ENTRIES=""
for entry in "${PRINCIPAL_ARRAY[@]}"; do
    if [ -n "$ACCESS_ENTRIES" ]; then
        ACCESS_ENTRIES="${ACCESS_ENTRIES},${entry}"
    else
        ACCESS_ENTRIES="${entry}"
    fi
done

# Build default ACL entries (mirror access entries)
DEFAULT_ENTRIES=""
for entry in "${PRINCIPAL_ARRAY[@]}"; do
    default_entry="default:${entry}"
    if [ -n "$DEFAULT_ENTRIES" ]; then
        DEFAULT_ENTRIES="${DEFAULT_ENTRIES},${default_entry}"
    else
        DEFAULT_ENTRIES="${default_entry}"
    fi
done

# Add default entries for user_obj, group_obj, mask, other
DEFAULT_ENTRIES="${DEFAULT_ENTRIES},default:user::rwx,default:group::${GROUP_PERMS},default:mask::rwx,default:other::---"

# Combine all entries (group:: uses the specified GROUP_PERMS)
ALL_ENTRIES="${ACCESS_ENTRIES},group::${GROUP_PERMS},mask::rwx,${DEFAULT_ENTRIES}"

echo "Step 3: Applying ACLs..."
echo "  ACL entries: $ALL_ENTRIES"
setfacl -m "$ALL_ENTRIES" "$WORKSPACE"

# Step 4: Verify
echo ""
echo "Step 4: Verification..."
echo "=== Directory metadata ==="
stat -c "Mode: %a (%A)  Owner: %U  Group: %G" "$WORKSPACE"
echo ""
echo "=== ACL configuration ==="
getfacl "$WORKSPACE"
echo ""
echo "=== Setup complete ==="
