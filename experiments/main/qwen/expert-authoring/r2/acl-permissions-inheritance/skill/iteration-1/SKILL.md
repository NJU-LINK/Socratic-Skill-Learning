---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspaces with correct ownership,
  setgid group propagation, per-principal access policies, and default ACL
  inheritance for newly created files and subdirectories.
---

# ACL Permissions & Inheritance Configuration

## Overview

This skill configures a shared workspace directory with POSIX ACLs so that
multiple principals (users and groups) receive precisely the access the policy
requires, and that access propagates correctly to all future descendants.

## Decision Framework

### 1. Parse the Policy

Extract these invariants from the task description:

| Element | What to identify |
|---|---|
| **Workspace path** | The directory to create/configure (e.g., `/srv/shared`) |
| **Owning group** | The group that owns the workspace (e.g., `editors`) |
| **Base mode** | The chmod value including setgid (e.g., `2770`) |
| **Full-access collaborators** | Named users/groups needing rwx |
| **Restricted principals** | Named users/groups with partial access (e.g., read + traverse only) |
| **Denied principals** | Everyone else (`other` class → `---`) |
| **Inheritance scope** | Whether ACLs must propagate to new files, new subdirs, or both |

### 2. Ensure Prerequisites

```bash
# Verify ACL tools are available
which setfacl getfacl
# Verify users and groups exist
id <user>; getent group <group>
```

### 3. Create the Workspace Directory

```bash
mkdir -p <WORKSPACE_PATH>
chown root:<OWNING_GROUP> <WORKSPACE_PATH>
chmod <BASE_MODE> <WORKSPACE_PATH>    # e.g., 2770 (setgid + rwx for owner/group, nothing for other)
```

Key points:
- `2` prefix = setgid bit → new items inherit the owning group
- Owner is typically `root` (or as specified)
- Group is the collaboration group
- Base mode `770` means owner and group have full access, others have none

### 4. Configure Access ACLs on the Directory

For each **full-access collaborator** (named user):
```bash
setfacl -m u:<user>:rwx <WORKSPACE_PATH>
```

For each **restricted principal**, map the requirement to ACL bits:

| Requirement | ACL permission |
|---|---|
| Traverse directories | `--x` minimum |
| List directory contents | `r--` minimum |
| Read files | `r--` |
| Execute scripts (when made executable) | `--x` |
| Create/modify/delete files | `-w-` |
| Create subdirectories | `-w-` on parent directory |

Typical restricted pattern (read + traverse, no write):
```bash
setfacl -m u:<user>:r-x <WORKSPACE_PATH>
```

You can combine multiple entries in one call:
```bash
setfacl -m u:<full_user1>:rwx,u:<full_user2>:rwx,u:<restricted_user>:r-x <WORKSPACE_PATH>
```

### 5. Configure Default ACLs for Inheritance

Default ACLs on a directory become the access ACLs of newly created children.
**This is the critical step for inheritance.**

Set default entries that mirror the access ACLs, plus defaults for the base
classes (owner, group, other, mask):

```bash
setfacl -d -m \
  u::rwx,\
  g::rwx,\
  o::---,\
  u:<full_user1>:rwx,\
  u:<full_user2>:rwx,\
  u:<restricted_user>:r-x \
  <WORKSPACE_PATH>
```

Explanation of each default entry:
- `d:u::rwx` — owner of new items gets full access
- `d:g::rwx` — owning group (propagated via setgid) gets full access
- `d:o::---` — others get no access
- `d:u:<user>:rwx` or `d:u:<user>:r-x` — named user entries propagate

The default mask is auto-calculated as the union of all named-user, named-group,
and owning-group entries (typically `rwx`). This ensures full-access users are
not clipped.

### 6. How Inheritance Works at Runtime

Understanding the interaction between default ACLs and file creation:

- **New subdirectory**: inherits full default ACL as both access ACL and its own
  default ACL. The setgid bit also propagates, so the group continues to be
  inherited. All permission bits (including execute for traversal) are preserved.

- **New regular file**: inherits the default ACL as its access ACL, but the
  **creation mode** from the `open()`/`creat()` syscall acts as an additional
  mask. Since programs typically create files with mode `0666` (no execute),
  the effective mask becomes `rw-`. This means:
  - Full-access users get `rw-` effective (no execute until `chmod +x`)
  - Restricted users with `r-x` default get `r--` effective (read only)
  - When a collaborator runs `chmod +x`, the mask expands and execute becomes
    effective for all entries that include it

This is the correct and expected behavior — scripts are executable only after
being explicitly marked so.

## Verification Checklist

After configuration, verify each requirement:

```bash
# 1. Directory ownership and setgid
ls -ld <WORKSPACE_PATH>
# Should show: drwxrws---+ root <group> ...
# The 's' in group execute position confirms setgid

# 2. Full ACL listing
getfacl <WORKSPACE_PATH>
# Check: access ACLs for all named users, default ACLs present, mask is rwx, other is ---

# 3. Test collaborator creates file
su -s /bin/bash <collab_user> -c "touch <WORKSPACE_PATH>/testfile"
ls -la <WORKSPACE_PATH>/testfile
# Group should be <OWNING_GROUP> (setgid working)
getfacl <WORKSPACE_PATH>/testfile
# Should show inherited ACL entries with mask rw-

# 4. Test collaborator creates subdirectory
su -s /bin/bash <collab_user> -c "mkdir <WORKSPACE_PATH>/testdir"
ls -ld <WORKSPACE_PATH>/testdir
getfacl <WORKSPACE_PATH>/testdir
# Should show: setgid set, full default ACLs propagated, all named user entries present

# 5. Test restricted user read access
su -s /bin/bash <restricted_user> -c "cat <WORKSPACE_PATH>/testfile"
# Should succeed

# 6. Test restricted user cannot write
su -s /bin/bash <restricted_user> -c "echo x >> <WORKSPACE_PATH>/testfile"
# Should fail: Permission denied

# 7. Test restricted user cannot create
su -s /bin/bash <restricted_user> -c "touch <WORKSPACE_PATH>/newfile"
# Should fail: Permission denied
su -s /bin/bash <restricted_user> -c "mkdir <WORKSPACE_PATH>/newdir"
# Should fail: Permission denied

# 8. Test unrelated user has no access
su -s /bin/bash <unrelated_user> -c "ls <WORKSPACE_PATH>/"
# Should fail: Permission denied

# 9. Test script execution for restricted user
su -s /bin/bash <collab_user> -c 'echo "#!/bin/sh" > <WORKSPACE_PATH>/script.sh && chmod +x <WORKSPACE_PATH>/script.sh'
su -s /bin/bash <restricted_user> -c "<WORKSPACE_PATH>/script.sh"
# Should succeed
```

## Common Pitfalls

1. **Forgetting default ACLs**: Access ACLs only apply to the directory itself.
   Without default ACLs, new files/dirs won't inherit any named-user entries.

2. **Forgetting the mask**: The ACL mask clips effective permissions. If the
   mask is too restrictive (e.g., `rw-` on the directory), even `rwx` named
   entries get clipped. The mask auto-recalculates on `setfacl -m` unless
   `-n` (no-mask) is passed.

3. **Setgid not propagating**: Setgid must be set on every subdirectory. With
   default ACLs and setgid on the parent, new subdirectories automatically
   inherit both. Without setgid, new items get the creator's primary group.

4. **Confusing ACL mask with group permission**: When ACLs are active, `ls -l`
   shows the ACL mask in the group permission field, not the owning group's
   actual permissions. Use `getfacl` for the real picture.

5. **Not setting `d:o::---`**: If the default other entry isn't explicitly set,
   it may inherit a permissive value from the system defaults.

6. **Creating test files when told not to**: Some tasks explicitly say "do not
   pre-create test files." The tests will create their own content. Only
   configure the directory and its ACLs.

## Generalization Notes

The approach above works for any combination of:

- **Multiple named users** with different permission levels
- **Named groups** (use `g:<group>:<perms>` instead of `u:<user>:<perms>`)
- **Mixed access** where some users get access through group membership and
  others through explicit ACL entries
- **Deeper directory trees** — default ACLs propagate recursively to any depth
- **Different base modes** — adjust the chmod value to match the policy
- **Multiple workspaces** — repeat the process for each path

The core pattern is always:
1. Create directory with correct ownership and setgid
2. Set access ACLs for the directory itself
3. Set default ACLs so children inherit the correct policy
4. Verify every behavioral requirement explicitly
