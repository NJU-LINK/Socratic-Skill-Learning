---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux for shared workspace directories with
  multi-principal access policies, default-ACL inheritance for descendants,
  setgid group propagation, and creation-mode-aware permission scoping.
  Generalizes across arbitrary principal topologies (named users, groups,
  mixed), permission models (rwx combinations, mask-restricted, read-only
  traversal principals), and inheritance depths (single directory, deep
  trees, multi-generation propagation).
---

# POSIX ACL Shared Workspace Configuration

## Overview

This skill configures Linux POSIX ACLs on a shared directory so that:
- Named collaborators get specified access (read/write/execute)
- Restricted principals get limited access (e.g., read + traverse only)
- Unspecified principals are denied all access
- Permissions propagate correctly to newly created files and subdirectories
- Group ownership propagates via setgid

## Core POSIX ACL Concepts

### Entry Types
- **user::** (user_obj) — maps to owner permission bits
- **group::** (group_obj) — maps to owning group permission bits; also bounded by mask
- **other::** — maps to other permission bits
- **user:NAME:PERMS** — named user entry; effective = PERMS AND mask
- **group:NAME:PERMS** — named group entry; effective = PERMS AND mask
- **mask::PERMS** — upper bound for all named entries AND group_obj

### Access ACL vs Default ACL
- **Access ACL**: governs access to the object itself
- **Default ACL** (directories only): template inherited by new children
  - New subdirectory: gets parent's default ACL as BOTH its access ACL AND its own default ACL (propagation continues)
  - New file: gets parent's default ACL as its access ACL only (no default ACL on files)

### Creation-Mode Intersection (Critical)
When a new object is created:
```
final(entry) = default_ACL(entry) AND requested_mode(entry)
final(mask)  = default_ACL(mask)  AND requested_mode(group_bits)
```
- Files are typically created with mode `0666` (no execute bit)
- Directories are typically created with mode `0777`
- This means a default ACL entry of `r-x` yields:
  - Effective `r--` on new files (read only — correct for read-only principals)
  - Effective `r-x` on new directories (traverse — correct for directory access)
  - Effective `r-x` on scripts that are later `chmod +x`'d (execute — correct for script execution)

### The ACL Check Algorithm (Critical for Understanding Access)

When a process accesses a file, the kernel checks ACL entries in this order:

1. **File owner matches process UID?** → Use `user::` (owner) entry. STOP.
2. **Named user entry matches process UID?** → Use that `user:NAME:` entry (bounded by mask). STOP.
3. **Process GID or supplementary groups match owning group?** → Use `group::` entry (bounded by mask). STOP.
4. **Process GID or supplementary groups match a named group?** → Use that `group:NAME:` entry (bounded by mask). STOP.
5. **Use `other::` entry.**

**Key insight**: The algorithm STOPS at the first match. If a user has a named user entry, group entries are NOT checked — even if the user is in the owning group.

**Example**: Alice is in the `editors` group (owning group). The ACL has:
- `user::rwx` (owner)
- `user:alice:rwx` (named user)
- `group::r-x` (owning group)
- `mask::rwx`

When alice accesses the file:
- Step 1: Is alice the file owner? No (root is owner).
- Step 2: Is there a `user:alice:` entry? YES → Use `user:alice:rwx` (effective: rwx AND mask::rwx = rwx). STOP.
- The `group::r-x` entry is NOT checked for alice.

This means named user entries take precedence over group entries. If you want alice to have different permissions than the owning group, you MUST give her a named user entry.

### Setgid Bit
- `chmod g+s` (or mode `2xxx`) ensures new items inherit the parent's group ownership
- Independent of ACLs — needed for group propagation alongside default ACLs

## Generalized Procedure

### Step 1: Analyze Requirements

Identify from the task specification:
1. **Workspace path** — the shared directory to configure
2. **Owning group** — the group that should own the workspace
3. **Base mode** — typically `2770` (setgid + rwx for owner and group, nothing for others)
4. **Principal inventory** — for each principal, determine:
   - Principal type: named user, named group, or other
   - Required permissions on the workspace directory itself
   - Required permissions on new files (considering creation-mode intersection)
   - Required permissions on new directories
   - Whether they need to create/delete objects (write permission on directory)
5. **Deny policy** — what access (if any) should non-listed principals have? Typically `---`.
6. **Owning group permissions** — decide what `group::` should be:
   - If ALL members of the owning group should have access: set `group::rwx` (or appropriate perms)
   - If ONLY named users should have access (not all group members): set `group::---`
   - **Critical**: Any member of the owning group who does NOT have a named user entry will get `group::` permissions. If this is too broad, restrict `group::`.

### Step 2: Create Directory Structure

```bash
mkdir -p <workspace_path>
chown <owner>:<group> <workspace_path>
chmod <base_mode> <workspace_path>
```

The base mode should include:
- setgid bit (2000) for group ownership inheritance
- Owner permissions (user_obj) matching the owner's needs
- Group permissions (group_obj) matching the owning group's needs
- Other permissions matching the deny policy (typically `---`)

### Step 3: Set Access ACLs

Set ACL entries on the workspace directory for each named principal:

```bash
setfacl -m <entry1>,<entry2>,... <workspace_path>
```

Where entries are of the form:
- `user:NAME:rwx` for full-access users
- `user:NAME:r-x` for read/traverse-only users
- `group:NAME:rwx` for full-access groups
- etc.

### Step 4: Set Default ACLs for Inheritance

Mirror the access ACL entries as default ACLs so children inherit them:

```bash
setfacl -m default:user:NAME:rwx,default:user:NAME:r-x,... <workspace_path>
```

Also set default entries for user_obj, group_obj, mask, and other:

```bash
# These are often auto-created, but be explicit:
setfacl -m default:user::rwx,default:group::rwx,default:other::--- <workspace_path>
```

### Step 5: Set the Mask

The mask must be at least as permissive as the most-privileged named entry:

```bash
setfacl -m mask::rwx,default:mask::rwx <workspace_path>
```

**Important**: When using `setfacl -m`, the mask is auto-recalculated as the union of all named entries and group_obj. To override this, include `mask::PERMS` in the same command. The mask must accommodate the maximum permissions any named entry requires.

### Step 6: Verify

```bash
getfacl <workspace_path>
```

Expected output should show:
- All named user/group entries with correct permissions
- mask matching the most permissive named entry
- other::--- (or whatever the deny policy requires)
- Matching default: entries for inheritance
- flags: -s- indicating setgid

### Step 7: Behavioral Verification

Test with representative operations:

```bash
# Full-access user should be able to create files/dirs
su -c "touch <workspace>/testfile" <collaborator>
su -c "mkdir <workspace>/testdir" <collaborator>

# Restricted user should be able to read/traverse but not write
su -c "ls <workspace>/" <restricted_user>          # should succeed
su -c "cat <workspace>/testfile" <restricted_user>  # should succeed
su -c "touch <workspace>/newfile" <restricted_user> # should FAIL

# Check inheritance on new objects
getfacl <workspace>/testfile   # should show inherited ACLs with mask rw-
getfacl <workspace>/testdir    # should show inherited ACLs + default ACLs
```

## Design Patterns for Common Topologies

### Pattern A: Collaborators + Read-Only Observer
- Collaborators: `user:NAME:rwx` in both access and default ACLs
- Observer: `user:NAME:r-x` in both access and default ACLs
- Creation-mode intersection handles the rest: observer gets `r--` on files, `r-x` on dirs

### Pattern B: Group-Based Collaboration
- Use `group:NAME:rwx` instead of individual user entries
- Add users to the group: `usermod -aG <group> <user>`
- Still need default ACL for the group: `default:group:NAME:rwx`
- Mask must cover group permissions

### Pattern C: Mixed Users and Groups
- Some principals get access via group membership, others via explicit named user entries
- **The ACL check algorithm is first-match-wins** (see above): named user entries are checked BEFORE group entries
- If a user has a named user entry, group entries (including owning group) are NOT checked for that user
- This means: to give a group member DIFFERENT permissions than the group, add a named user entry
- Example: alice is in `editors` group (group::r-x), but needs rwx → add `user:alice:rwx`
- The named user entry overrides the group entry for alice specifically

### Pattern D: Explicit Deny for Specific Principals
- POSIX ACLs don't have explicit "deny" entries
- To deny a specific user: don't give them any named entry AND ensure `other::---`
- To deny a group: don't include them in any matching group AND ensure `other::---`
- If a user matches both a named entry and a group entry, the named user entry takes precedence

### Pattern E: Mask-Restricted Effective Permissions
- Set named entries with desired maximum permissions
- Set mask lower to restrict all named entries uniformly
- Example: `user:alice:rwx` + `mask::r-x` → alice's effective is `r-x`
- Useful when you want to temporarily restrict without removing entries

### Pattern F: Named Users Only (No Group Access)
- If you want ONLY specific named users to have access (not all members of the owning group):
  - Set `group::---` (or minimum required permissions)
  - Set `default:group::---` (or minimum required)
  - Give each authorized user a named user entry: `user:NAME:rwx`
  - This ensures that even if someone is added to the owning group, they won't get access unless explicitly added as a named user
- **Important**: The current v01 example uses `group::rwx` because alice and bob are the only editors. If the task requires restricting access to only named users (excluding other group members), use `group::---` instead.
- **Verification**: Test with a user who is in the owning group but NOT in the access policy — they should be denied access.

## Handling Edge Cases

### Deeper Directory Trees
Default ACLs propagate automatically: subdirectories inherit the parent's default ACL as both their access ACL and their own default ACL. No special configuration needed for depth.

### Different File vs Directory Permissions
The creation-mode intersection naturally handles this:
- Default `rwx` → files get `rw-`, directories get `rwx`
- Default `r-x` → files get `r--`, directories get `r-x`
- If you need execute on files too, the creating process must request it (e.g., `open()` with mode `0777` or `chmod +x` after creation)

### Creator Identity and Group Propagation
- setgid ensures all new items get the parent's group regardless of creator's primary group
- Default ACLs ensure all new items get the correct ACL entries regardless of creator's umask
- Both mechanisms work together independently

### Umask Interaction
- When a directory has default ACLs, the creating process's umask is **ignored**
- The default ACL fully determines the new object's permissions (intersected with creation mode)
- This is a key advantage of default ACLs over traditional Unix permissions

### Recursive ACL Application
- If the workspace already has existing content, use `setfacl -R` to apply ACLs recursively:
  ```bash
  setfacl -R -m user:alice:rwx,user:bob:rwx /srv/shared
  ```
- Use `setfacl -R -m d:user:alice:rwx` to set default ACLs recursively on all subdirectories
- **Caution**: `-R` applies to ALL existing files and directories. Review before running.
- For new content created after default ACLs are set, no recursive application is needed — inheritance handles it automatically.

### Idempotent Reconfiguration
- To reset a workspace to a clean state before re-applying ACLs:
  ```bash
  setfacl -b <workspace>   # Remove all ACLs
  chmod <base_mode> <workspace>  # Reset base permissions
  # Then re-apply ACLs from scratch
  ```
- `setfacl -b` removes all extended ACL entries (named users, named groups, mask) but keeps base entries (user_obj, group_obj, other)

## Setup Script

A parameterized setup script is provided at `setup-workspace.sh` in this skill package. Usage:

```bash
./setup-workspace.sh <workspace_path> <owner> <group> <base_mode> <group_perms> <principal_entries>

# Example for v01 (all editors get access via group::):
./setup-workspace.sh /srv/shared root editors 2770 rwx "user:alice:rwx,user:bob:rwx,user:runner:r-x"

# Example with named users only (group members without named entries get no access):
./setup-workspace.sh /srv/shared root editors 2770 --- "user:alice:rwx,user:bob:rwx,user:runner:r-x"

# Example with group-based principal:
./setup-workspace.sh /srv/workspace root devs 2770 rwx "group:devteam:rwx,user:observer:r-x"
```

The script handles directory creation, ACL cleanup, ownership, and verification. The `group_perms` parameter controls whether owning group members get access through `group::` — use `rwx` if all group members should have access, or `---` if only named users should have access.

## Complete Example (v01 Seed)

Workspace: `/srv/shared`, group: `editors`, setgid mode `2770`
- alice, bob: full rwx
- runner: read + traverse (r-x), no create/delete/modify
- Others: no access

```bash
# Create and configure directory
mkdir -p /srv/shared
chown root:editors /srv/shared
chmod 2770 /srv/shared

# Set all ACLs in one command (access + default + mask)
# IMPORTANT: setfacl requires comma-separated entries with NO trailing commas
# and NO commas at line-continuation boundaries. Use one line or careful formatting:
setfacl -m user:alice:rwx,user:bob:rwx,user:runner:r-x,mask::rwx,default:user::rwx,default:user:alice:rwx,default:user:bob:rwx,default:user:runner:r-x,default:group::rwx,default:mask::rwx,default:other::--- /srv/shared
```

Result verification with `getfacl /srv/shared`:
```
user::rwx
user:alice:rwx
user:bob:rwx
user:runner:r-x
group::rwx
mask::rwx
other::---
default:user::rwx
default:user:alice:rwx
default:user:bob:rwx
default:user:runner:r-x
default:group::rwx
default:mask::rwx
default:other::---
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Named user can't access despite ACL entry | Mask too restrictive | Increase mask to cover entry's permissions |
| New files don't inherit ACLs | No default ACL set | Add `default:` entries |
| New files have wrong group | No setgid bit | `chmod g+s` on parent |
| User can write but shouldn't | Write permission on directory ACL | Remove `w` from that principal's entry |
| Can't traverse to subdirectory | Missing `x` on directory | Ensure `x` in access ACL for directory |
| Execute on scripts doesn't work | File created without `x` bit | Creator must `chmod +x` or create with execute mode |
| umask seems to affect ACL children | No default ACL (falls back to umask) | Set default ACLs on parent |
