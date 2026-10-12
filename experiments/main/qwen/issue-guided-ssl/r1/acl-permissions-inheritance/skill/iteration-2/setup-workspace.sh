#!/bin/bash
# POSIX ACL Shared Workspace Setup Script
# This script configures a shared workspace with POSIX ACLs for multi-principal access.
#
# Usage: ./setup-workspace.sh <workspace_path> <group> <base_mode> <principal_entries>
#
# Example for v01:
#   ./setup-workspace.sh /srv/shared editors 2770 \
#     "user:alice:rwx,user:bob:rwx,user:runner:r-x"
#
# Parameters:
#   workspace_path  - Path to the shared directory
#   group           - Owning group name
#   base_mode       - Base permissions (e.g., 2770 for setgid + rwx for owner/group)
#   principal_entries - Comma-separated ACL entries for named principals
#                       (e.g., "user:alice:rwx,user:bob:rwx,user:runner:r-x")

set -euo pipefail

if [ $# -lt 4 ]; then
    echo "Usage: $0 <workspace_path> <group> <base_mode> <principal_entries>"
    echo ""
    echo "Example:"
    echo "  $0 /srv/shared editors 2770 \"user:alice:rwx,user:bob:rwx,user:runner:r-x\""
    exit 1
fi

WORKSPACE="$1"
GROUP="$2"
BASE_MODE="$3"
PRINCIPALS="$4"

echo "=== POSIX ACL Workspace Setup ==="
echo "Workspace: $WORKSPACE"
echo "Group: $GROUP"
echo "Base mode: $BASE_MODE"
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
chown root:"$GROUP" "$WORKSPACE"
chmod "$BASE_MODE" "$WORKSPACE"

# Step 3: Build ACL command
# Parse principal entries and create both access and default ACLs
echo "Step 3: Building ACL entries..."

# Extract individual principal entries
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
DEFAULT_ENTRIES="${DEFAULT_ENTRIES},default:user::rwx,default:group::rwx,default:mask::rwx,default:other::---"

# Combine all entries
ALL_ENTRIES="${ACCESS_ENTRIES},mask::rwx,${DEFAULT_ENTRIES}"

echo "  ACL entries: $ALL_ENTRIES"
echo ""

# Step 4: Apply ACLs
echo "Step 4: Applying ACLs..."
setfacl -m "$ALL_ENTRIES" "$WORKSPACE"

# Step 5: Verify
echo "Step 5: Verifying configuration..."
echo ""
echo "=== Directory metadata ==="
stat -c "Mode: %a (%A)  Owner: %U  Group: %G" "$WORKSPACE"
echo ""
echo "=== ACL configuration ==="
getfacl "$WORKSPACE"
echo ""
echo "=== Setup complete ==="
