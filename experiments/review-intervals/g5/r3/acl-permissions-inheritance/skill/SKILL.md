---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on a shared Linux workspace so that multiple principals
  (named users and groups) receive distinct access levels, with correct
  inheritance to newly created files and subdirectories via default ACLs and
  setgid group propagation.
---

# ACL Permissions Inheritance

## Problem

You must configure a shared directory on Linux so that:

- A set of **collaborators** (named users and/or groups) have full read/write/execute access.
- One or more **restricted principals** have partial access (e.g., read + traverse, but not write or create).
- **Everyone else** is denied access.
- These permissions **inherit correctly** to all newly created files and subdirectories, at any depth.

This requires coordinating three Linux mechanisms: POSIX ACLs (access + default), the setgid bit for group propagation, and the interaction between file creation modes and ACL masks.

## Quick Execution Summary

For experienced practitioners, here is the condensed command sequence. Details and rationale follow in the Method section.

```bash
# 1. Pre-flight: ensure users/groups exist
getent group <group> || groupadd <group>
id <user> >/dev/null 2>&1 || useradd -m <user>
usermod -aG <group> <collaborator>   # for each collaborator

# 2. Create workspace (idempotent)
mkdir -p <workspace>
chown <owner>:<group> <workspace>
chmod 2770 <workspace>
setfacl -b <workspace> 2>/dev/null || true   # clear stale ACLs

# 3. Access ACLs
setfacl -m u::rwx,g::rwx,o::--- <workspace>
setfacl -m u:<collab1>:rwx,u:<collab2>:rwx <workspace>
setfacl -m u:<restricted>:<perms> <workspace>
setfacl -m m::rwx <workspace>

# 4. Default ACLs (mirror access ACLs)
setfacl -d -m u::rwx,g::rwx,o::--- <workspace>
setfacl -d -m u:<collab1>:rwx,u:<collab2>:rwx <workspace>
setfacl -d -m u:<restricted>:<perms> <workspace>
setfacl -d -m m::rwx <workspace>

# 5. Verify
getfacl <workspace>
```

## Method

### Step 1: Parse the Task Requirements

Identify from the task description:

| Dimension | What to extract |
|-----------|----------------|
| **Workspace** | The path to the shared directory |
| **Owning group** | The group that should own the directory and be propagated via setgid |
| **Collaborators** | Users/groups that need full rwx access |
| **Restricted principals** | Users with partial permissions (e.g., r-x for read+traverse) |
| **Denied principals** | Everyone else — typically `other::---` |
| **Inheritance depth** | Whether the workspace is a single directory or a deep tree |

### Step 2: Pre-flight Checks and Directory Creation

Before creating the directory, ensure all required users and groups exist:

```bash
# Ensure the owning group exists
getent group <group> || groupadd <group>

# Ensure all users exist
for user in <collaborator1> <collaborator2> <restricted1>; do
    id "$user" >/dev/null 2>&1 || useradd -m "$user"
done

# Add collaborators to the owning group
for user in <collaborator1> <collaborator2>; do
    usermod -aG <group> "$user"
done
```

Now create the directory (idempotent — safe if it already exists):

```bash
mkdir -p <workspace_path>
chown <owner>:<group> <workspace_path>
chmod 2770 <workspace_path>   # rwxrws--- with setgid

# Clear any stale ACLs from a previous configuration
setfacl -b <workspace_path> 2>/dev/null || true
```

**Why clear existing ACLs?** If the directory already exists from a previous attempt or a different configuration, it may have ACL entries that conflict with your new policy. Clearing them first ensures a clean slate. This is especially important for idempotent re-runs or when working with pre-existing directories.

**Why setgid?** The setgid bit on a directory causes all newly created files and subdirectories within it to inherit the directory's group ownership, rather than the creating process's primary group. This ensures that collaborators who are members of the owning group always have group-level access.

**Why `chmod` before `setfacl`?** When a file/directory has ACLs, `chmod` modifies the **mask** entry, not the traditional group permission bits. If you run `chmod` after setting ACLs, you can accidentally change the mask and corrupt your named entries' effective permissions. Always set the base mode first, then layer ACLs on top.

### Step 3: Set Access ACLs (Controls the Directory Itself)

```bash
# Owner gets full access
setfacl -m u::rwx <workspace>

# Owning group gets full access
setfacl -m g::rwx <workspace>

# Each collaborator gets full access
setfacl -m u:<collaborator>:rwx <workspace>
# Or for group-based collaborators:
setfacl -m g:<collab_group>:rwx <workspace>

# Restricted principals get their designated permissions
setfacl -m u:<restricted>:<perms> <workspace>

# Everyone else gets nothing
setfacl -m o::--- <workspace>

# Set the mask to rwx so it doesn't restrict named entries
setfacl -m m::rwx <workspace>
```

### Step 4: Set Default ACLs (Inherited by New Children)

Default ACLs on a directory define the access ACL that newly created children will receive. For directories, the default ACLs also propagate to the child's own default ACLs (cascading inheritance).

```bash
# Mirror the access ACL structure as defaults
setfacl -d -m u::rwx <workspace>
setfacl -d -m g::rwx <workspace>
setfacl -d -m u:<collaborator>:rwx <workspace>
setfacl -d -m u:<restricted>:<perms> <workspace>
setfacl -d -m o::--- <workspace>
setfacl -d -m m::rwx <workspace>
```

**Critical insight about creation modes and the mask:**

When a new file is created, its access ACL is computed as: `default_ACL_entries AND requested_mode`. The requested mode comes from the creating system call:
- `open()` for regular files typically requests mode `0666` (no execute)
- `mkdir()` requests mode `0777` (with execute)
- Scripts created with explicit execute permission request `0777`

This means a default ACL entry of `user:runner:r-x` produces:
- **Regular file** (mode 0666): `r-x AND rw- = r--` → read only ✓
- **Executable script** (mode 0777): `r-x AND rwx = r-x` → read + execute ✓
- **Subdirectory** (mode 0777): `r-x AND rwx = r-x` → traverse only ✓

The creation mode acts as a natural gate for the execute bit. You don't need separate ACL entries for files vs. directories.

### Step 5: Ensure Collaborators Are in the Owning Group

```bash
usermod -aG <group> <collaborator>
```

This provides a backup layer: even if ACL entries were somehow lost, group membership + setgid ensures collaborators retain access through the `group::rwx` entry.

### Step 6: Verify

```bash
# Check ACL structure
getfacl <workspace>

# Test as each user
su -s /bin/bash <user> -c '<operation>'

# Test inheritance by creating files/dirs and checking their ACLs
su -s /bin/bash <collaborator> -c 'touch <workspace>/testfile'
getfacl <workspace>/testfile
rm <workspace>/testfile
```

## Key Principles

1. **Order matters**: `chmod` before `setfacl`. After ACLs exist, `chmod` modifies the mask.
2. **Default ACLs mirror access ACLs**: Set the same structure as defaults to ensure consistent inheritance.
3. **Mask = rwx**: Unless the task specifically requires constraining effective permissions, set the mask to `rwx` so named entries are not inadvertently restricted.
4. **r-x is the universal "read + conditional execute" pattern**: The file creation mode naturally gates the execute bit, so a single `r-x` default ACL entry handles files, scripts, and directories correctly.
5. **Setgid + group ACL = defense in depth**: Setgid ensures group propagation; the group ACL entry ensures group members have the expected access.
6. **`other::---` denies everyone else**: This is the standard way to exclude non-collaborators.
7. **Create/delete is a directory-level operation**: In POSIX, creating, deleting, or renaming a file requires write permission on the **parent directory**, not on the file itself. To prevent a user from creating or deleting files, deny them write (`w`) on the directory. This is why `r-x` on the directory blocks all create/delete operations regardless of file-level permissions.
8. **Idempotency matters**: Always clear existing ACLs with `setfacl -b` before setting new ones. Check if users/groups exist before assuming they do. Use `mkdir -p` instead of `mkdir`. These practices make the configuration safe to re-run and robust against pre-existing state.

## Variation Handling

### Different access_policy_topology
- Multiple restricted users: add a `user:<name>:<perms>` entry for each
- Group-based collaborators: use `g:<group>:<perms>` instead of (or in addition to) named user entries
- Mixed user+group access: some principals may get access through group membership while others need explicit named entries
- Additional denied principals: add explicit `user:<name>:---` entries for specific denials beyond the generic `other::---`

### Different permission_model
- Read-only collaborators: use `r--` or `r-x` as appropriate
- Write-without-execute: use `rw-` for file-only write access
- Directory traversal without file read: use `--x` (unusual but possible)
- Mask-constrained permissions: set `m::rw-` to cap all named entries at read+write
- **Shared-write with mutual protection**: If multiple collaborators need write access but shouldn't delete each other's files, combine write ACLs with the **sticky bit** (mode `3770` instead of `2770`). The sticky bit allows deletion only by the file's owner, the directory's owner, or root.
- **Explicit deny entries**: If a specific named user must be denied even when they belong to a group that has access, add `user:<name>:---` as an explicit ACL entry. Named user entries are checked before group entries in the POSIX ACL evaluation order.

### Different inheritance_and_group_propagation
- Deep directory trees: default ACLs cascade automatically to subdirectories' own default ACLs
- Multiple workspace roots: apply the same pattern to each root directory
- Different creator identities: setgid ensures group propagation regardless of who creates
- Creation order independence: default ACLs apply regardless of which user creates first

## Scripts

- `scripts/configure-acls.sh` — Parameterized script that implements this method for any combination of principals and permissions.

## References

- `references/acl-mechanics.md` — Detailed explanation of POSIX ACL mechanics, the mask, creation mode interaction, and inheritance.
