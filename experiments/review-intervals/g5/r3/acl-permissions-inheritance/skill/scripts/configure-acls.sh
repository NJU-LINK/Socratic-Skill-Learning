#!/usr/bin/env bash
# configure-acls.sh — Configure POSIX ACLs on a shared workspace with
# per-principal access policies and correct inheritance via default ACLs.
#
# Usage:
#   configure-acls.sh <workspace> <group> <collaborators> [restricted_specs...] [options]
#
# Arguments:
#   workspace       Path to the shared directory (created if absent)
#   group           Owning group for the directory (created if absent)
#   collaborators   Comma-separated list of users who get full rwx access
#                   (also added to the owning group)
#   restricted_specs  Zero or more arguments of the form "user:perms" or "group:g_perms"
#                     e.g. "runner:r-x" or "group:viewers:r-x"
#
# Options:
#   --owner <user>       Directory owner (default: root)
#   --mask <perms>       ACL mask entry (default: rwx)
#   --other <perms>      other:: entry (default: ---)
#   --collab-group <grp> Additional group granted rwx (can repeat)
#   --no-setgid          Skip setting the setgid bit
#   --sticky             Add sticky bit (only file owners can delete their files)
#   --base-mode <mode>   Override base mode (default: 2770 or 1770 if --no-setgid)
#
# Examples:
#   # v01-style setup
#   configure-acls.sh /srv/shared editors "alice,bob" "runner:r-x"
#
#   # Multiple restricted users, group-based collaborator
#   configure-acls.sh /data/project engineers "dev1,dev2" \
#       "group:contractors:r-x" "auditor:r--"
#
#   # Custom mask to constrain all named entries
#   configure-acls.sh /srv/shared editors "alice,bob" "runner:r-x" --mask rw-

set -euo pipefail

# ─── Argument parsing ────────────────────────────────────────────────
WORKSPACE="${1:?Usage: configure-acls.sh <workspace> <group> <collaborators> [restricted_specs...]}"
GROUP="${2:?Missing group argument}"
COLLABORATORS="${3:?Missing collaborators argument}"
shift 3

RESTRICTED_USERS=()
RESTRICTED_PERMS=()
RESTRICTED_GROUPS=()
RESTRICTED_GROUP_PERMS=()
EXTRA_COLLAB_GROUPS=()
OWNER="root"
MASK="rwx"
OTHER="---"
SETGID=true
STICKY=false
BASE_MODE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --owner)
            OWNER="$2"; shift 2 ;;
        --mask)
            MASK="$2"; shift 2 ;;
        --other)
            OTHER="$2"; shift 2 ;;
        --collab-group)
            EXTRA_COLLAB_GROUPS+=("$2"); shift 2 ;;
        --no-setgid)
            SETGID=false; shift ;;
        --sticky)
            STICKY=true; shift ;;
        --base-mode)
            BASE_MODE="$2"; shift 2 ;;
        group:*)
            # Format: group:<groupname>:<perms>
            spec="${1#group:}"
            gname="${spec%%:*}"
            gperms="${spec#*:}"
            RESTRICTED_GROUPS+=("$gname")
            RESTRICTED_GROUP_PERMS+=("$gperms")
            shift ;;
        *:*)
            # Format: user:perms
            uname="${1%%:*}"
            uperms="${1#*:}"
            RESTRICTED_USERS+=("$uname")
            RESTRICTED_PERMS+=("$uperms")
            shift ;;
        *)
            echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

# Determine base mode
if [[ -z "$BASE_MODE" ]]; then
    MODE_PREFIX="0"
    if $SETGID && $STICKY; then
        MODE_PREFIX="3"
    elif $SETGID; then
        MODE_PREFIX="2"
    elif $STICKY; then
        MODE_PREFIX="1"
    fi
    BASE_MODE="${MODE_PREFIX}770"
fi

# ─── Helper functions ────────────────────────────────────────────────
ensure_group() {
    local grp="$1"
    if ! getent group "$grp" >/dev/null 2>&1; then
        echo "[INFO] Creating group: $grp"
        groupadd "$grp"
    fi
}

ensure_user() {
    local usr="$1"
    if ! id "$usr" >/dev/null 2>&1; then
        echo "[INFO] Creating user: $usr"
        useradd -m "$usr"
    fi
}

add_user_to_group() {
    local usr="$1" grp="$2"
    if ! id -nG "$usr" 2>/dev/null | tr ' ' '\n' | grep -qx "$grp"; then
        echo "[INFO] Adding $usr to group $grp"
        usermod -aG "$grp" "$usr"
    fi
}

# ─── Step 1: Ensure users and groups exist ──────────────────────────
echo "=== Step 1: Ensuring users and groups ==="
ensure_group "$GROUP"

IFS=',' read -ra COLLAB_ARRAY <<< "$COLLABORATORS"
for user in "${COLLAB_ARRAY[@]}"; do
    ensure_user "$user"
    add_user_to_group "$user" "$GROUP"
done

for grp in "${EXTRA_COLLAB_GROUPS[@]}"; do
    ensure_group "$grp"
done

for user in "${RESTRICTED_USERS[@]}"; do
    ensure_user "$user"
done

for grp in "${RESTRICTED_GROUPS[@]}"; do
    ensure_group "$grp"
done

# ─── Step 2: Create directory with correct ownership and mode ────────
echo "=== Step 2: Creating workspace directory ==="
mkdir -p "$WORKSPACE"
chown "$OWNER:$GROUP" "$WORKSPACE"
chmod "$BASE_MODE" "$WORKSPACE"
echo "  Directory: $WORKSPACE"
echo "  Mode: $(stat -c '%A' "$WORKSPACE")"
echo "  Owner: $(stat -c '%U:%G' "$WORKSPACE")"

# ─── Step 3: Remove any existing ACLs (clean slate) ─────────────────
echo "=== Step 3: Setting access ACLs ==="
setfacl -b "$WORKSPACE" 2>/dev/null || true

# Build access ACL command
ACL_ENTRIES=()
ACL_ENTRIES+=("u::rwx")
ACL_ENTRIES+=("g::rwx")

# Collaborators get full access
for user in "${COLLAB_ARRAY[@]}"; do
    ACL_ENTRIES+=("u:${user}:rwx")
done

# Extra collaborator groups
for grp in "${EXTRA_COLLAB_GROUPS[@]}"; do
    ACL_ENTRIES+=("g:${grp}:rwx")
done

# Restricted users
for i in "${!RESTRICTED_USERS[@]}"; do
    ACL_ENTRIES+=("u:${RESTRICTED_USERS[$i]}:${RESTRICTED_PERMS[$i]}")
done

# Restricted groups
for i in "${!RESTRICTED_GROUPS[@]}"; do
    ACL_ENTRIES+=("g:${RESTRICTED_GROUPS[$i]}:${RESTRICTED_GROUP_PERMS[$i]}")
done

# Mask and other
ACL_ENTRIES+=("m::${MASK}")
ACL_ENTRIES+=("o::${OTHER}")

# Apply access ACLs in one command
setfacl -m "$(IFS=,; echo "${ACL_ENTRIES[*]}")" "$WORKSPACE"

# ─── Step 4: Set default ACLs (inheritance) ─────────────────────────
echo "=== Step 4: Setting default ACLs ==="
DEFAULT_ENTRIES=()
DEFAULT_ENTRIES+=("u::rwx")
DEFAULT_ENTRIES+=("g::rwx")

for user in "${COLLAB_ARRAY[@]}"; do
    DEFAULT_ENTRIES+=("u:${user}:rwx")
done

for grp in "${EXTRA_COLLAB_GROUPS[@]}"; do
    DEFAULT_ENTRIES+=("g:${grp}:rwx")
done

for i in "${!RESTRICTED_USERS[@]}"; do
    DEFAULT_ENTRIES+=("u:${RESTRICTED_USERS[$i]}:${RESTRICTED_PERMS[$i]}")
done

for i in "${!RESTRICTED_GROUPS[@]}"; do
    DEFAULT_ENTRIES+=("g:${RESTRICTED_GROUPS[$i]}:${RESTRICTED_GROUP_PERMS[$i]}")
done

DEFAULT_ENTRIES+=("m::${MASK}")
DEFAULT_ENTRIES+=("o::${OTHER}")

setfacl -d -m "$(IFS=,; echo "${DEFAULT_ENTRIES[*]}")" "$WORKSPACE"

# ─── Step 5: Verify ─────────────────────────────────────────────────
echo "=== Step 5: Verification ==="
echo ""
echo "Directory listing:"
ls -la "$(dirname "$WORKSPACE")" | grep "$(basename "$WORKSPACE")"
echo ""
echo "ACL entries:"
getfacl "$WORKSPACE" 2>/dev/null
echo ""
echo "=== Configuration complete ==="
