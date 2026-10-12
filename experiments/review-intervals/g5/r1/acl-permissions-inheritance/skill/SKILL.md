---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspace directories with correct
  permission inheritance for files and subdirectories, setgid group propagation,
  and differentiated access for named users, groups, collaborators, and
  restricted principals.
---

# ACL Permissions Inheritance

## Overview

This skill configures Linux POSIX ACLs on shared workspace directories so that:
- A collaborating group has full access to the workspace and all descendants
- Named users have specific differentiated permissions (e.g., read-only, read+execute)
- Permissions propagate correctly to newly created files AND subdirectories
- Setgid ensures group ownership inheritance
- Unauthorized users have no access

## Quick Decision Procedure

For any ACL workspace task, follow these steps:

### 1. Parse Requirements
Extract from the task:
- **Workspace path** (e.g., `/srv/shared`)
- **Owning group** (e.g., `editors`)
- **Collaborators** with full access → `rwx`
- **Restricted users** with limited access → `r-x` (read+traverse) or `r--` (read-only)
- **Explicitly denied users** → `---` (beyond generic `other`)

### 2. Decide: Named User vs Named Group Entries
For each principal, decide whether to use named user (`u:<name>:<perms>`) or named group (`g:<group>:<perms>`) entries:

**Use named user entries when:**
- You need per-user granularity (different perms for alice vs bob)
- The principal must bypass group-based evaluation entirely
- The principal is NOT a member of the collaborating group (like runner)
- Restricted users who must be kept out of the collaborating group

**Use named group entries when:**
- All team members need the same access level
- You want to manage access by adding/removing users from groups
- The owning group (`group::`) already provides the right access

**Practical rule:**
- Collaborators IN the owning group: may not need named user entries if `group::rwx` suffices
- Collaborators NOT in the owning group: MUST have named user entries
- Restricted users: MUST have named user entries AND be excluded from the collaborating group

**Example patterns:**
- v01 pattern: alice/bob in editors (get `group::rwx`), runner NOT in editors (needs `u:runner:r-x`)
- Mixed pattern: alice in editors (no named entry), charlie NOT in editors (needs `u:charlie:rwx`)
- Team pattern: `g:devteam:rwx` for all developers, `u:auditor:r-x` for read-only access

### 3. Execute Setup Script
```bash
# Create workspace with correct ownership and setgid
mkdir -p <workspace>
chown <owner>:<group> <workspace>
chmod 2770 <workspace>

# Set access ACLs (use u: for named users, g: for named groups)
setfacl -m u:<collab1>:rwx <workspace>
setfacl -m u:<collab2>:rwx <workspace>
setfacl -m u:<restricted>:r-x <workspace>
# OR use group entries: setfacl -m g:<team>:rwx <workspace>
setfacl -m o::--- <workspace>

# Set default ACLs (mirror access policy for inheritance)
setfacl -d -m u::rwx <workspace>
setfacl -d -m g::rwx <workspace>
setfacl -d -m u:<collab1>:rwx <workspace>
setfacl -d -m u:<collab2>:rwx <workspace>
setfacl -d -m u:<restricted>:r-x <workspace>
# OR mirror group entries: setfacl -d -m g:<team>:rwx <workspace>
setfacl -d -m o::--- <workspace>
```

### 4. Verify
```bash
getfacl <workspace>          # Check access + default sections
stat <workspace>             # Verify setgid and mode
```

## Core Concepts

### POSIX ACL Structure
- **Access ACL**: controls access to this specific object
- **Default ACL**: (directories only) template applied to newly created children
- Subdirectories inherit the default ACL as their own default ACL, enabling multi-level propagation

### The ACL Mask — Critical Ceiling
The mask is the **upper bound** for effective permissions of:
- All named user entries (`u:alice:rwx`)
- All named group entries
- The owning group entry (`group::rwx`)

The mask does NOT limit the file owner (`user::`) or `other::`.

**Key rule**: `setfacl -m` auto-recalculates the mask as the union of all named entries + owning group (unless you use `-n`). Avoid explicitly setting the mask unless you intentionally want to restrict permissions.

### File Creation Strips Execute
When a regular file is created, the **kernel strips the execute bit from ALL ACL entries** — including named user entries inherited from default ACLs.

- Default ACL `u:runner:r-x` → new file gets stored `u:runner:r-x` but mask is `rw-` → effective `r--`
- Default ACL `u:runner:r-x` → new directory gets `u:runner:r-x` with mask `rwx` → effective `r-x`

### chmod ↔ Mask Interaction — The Execute Grant Mechanism
When ACLs are present, `chmod` maps to ACL entries as follows:
- `user::` ← user bits of chmod
- **The mask** ← group bits of chmod (critical!)
- `other::` ← other bits of chmod

So `chmod +x` raises the mask to include `x`, unlocking execute for **all** mask-limited entries. The stored named user entry does NOT change — only the mask expands.

**This makes "restricted user can execute collaborator-approved scripts" work**:
- New files → runner gets `r--` effective (safe: no accidental execute)
- Files made executable by collaborators via `chmod +x` → mask becomes `rwx` → runner's stored `r-x` becomes effective `r-x`
- New subdirectories → runner gets `r-x` effective from the start

**Note**: `chmod +x` also sets `other::--x`. This is typically harmless because the parent directory's `other::---` blocks traversal. If strict file-level `other` permissions matter, use `setfacl -m m::rwx` instead.

### Setgid for Group Propagation
Setting setgid (`chmod g+s` or `chmod 2xxx`) ensures all new files and subdirectories inherit the directory's group ownership, regardless of the creator's primary group.

### Default ACL Propagation Rules
- **Files**: Default ACL entries become access ACL entries, with execute stripped by kernel
- **Directories**: Default ACL entries become both access ACL entries AND the new directory's own default ACL entries
- **Mask on files**: Set to `creation_mode & default_mask` (typically `rw-`)
- **Mask on directories**: Set to the default mask (typically `rwx`)

### ACL Matching Order (Critical for Mixed Topologies)
When the kernel evaluates access, it checks POSIX ACL entries in this strict order:

1. **File owner** (`user::`): If process UID matches file owner, use `user::` permissions. STOP.
2. **Named user entries** (`u:<name>:<perms>`): If process UID matches a named user entry, use that entry's permissions **masked by the ACL mask**. STOP.
3. **Owning group or named group entries**: If process is a member of the owning group or any named group, use the **most permissive** matching group entry, masked by the ACL mask. STOP.
4. **Other** (`other::`): Use `other::` permissions. STOP.

**Implication**: A named user entry completely bypasses all group-based evaluation. If you give `u:alice:rwx`, alice's access is `rwx & mask`, regardless of what group she's in.

**Practical consequence for mixed topologies:**
- If alice is in `editors` group AND has `u:alice:rwx`, alice gets `rwx & mask` (named user wins, group membership irrelevant)
- If alice is in `editors` group but has NO named user entry, alice gets `group::rwx & mask` (group-class evaluation)
- If runner is NOT in `editors` but has `u:runner:r-x`, runner gets `r-x & mask` (named user entry, no group fallback)
- If runner is NOT in `editors` and has NO named user entry, runner falls through to `other::---` (denied)

This is why the pattern "restricted users get named entries AND are excluded from collaborating group" works: it guarantees they're evaluated at step 2 (named user) with the exact permissions you want, never falling through to step 3 (group) where they might get more access.

## Implementation Details

### Prerequisites
```bash
# Verify users and groups exist
getent group <groupname>
id <username>

# Verify ACL tools are available
which setfacl getfacl
```

### Base Mode Options
- `2770`: owner rwx, group rwx, other ---, setgid (most common for shared workspaces)
- `2750`: owner rwx, group r-x, other ---, setgid (if group should not write)

### Permission Design Guide
| Requirement | ACL Entry | Notes |
|---|---|---|
| Full access (read/write/execute/traverse) | `rwx` | Can create, modify, delete, traverse |
| Read files + traverse directories | `r-x` | Can read, list, traverse; cannot modify |
| Read files only (no traverse) | `r--` | Can read files if path known; cannot list dirs |
| Write only (unusual) | `-wx` | Can create/modify but not read existing |
| No access | `---` | Explicitly denied |

### Default ACL Semantics
- `default:user::rwx`: New files/dirs get creator as owner with `rwx` (for dirs) or `rw-` (for files, kernel strips x)
- `default:group::rwx`: New files/dirs get owning group with `rwx` (for dirs) or `rw-` (for files)
- These should match the intended permissions for creators and the owning group

## Common Pitfalls and Solutions

### Pitfall 1: Mask Accidentally Restricting Permissions
If you explicitly set the mask (e.g., `setfacl -m m::r-x`), all named entries get capped. **Solution**: Let setfacl auto-calculate the mask.

### Pitfall 2: Expecting Execute on Files from Default ACLs Alone
Default ACL `r-x` does NOT give execute on newly created regular files — the kernel strips it. **Solution**: This is by design. Execute on specific files comes from `chmod +x` which raises the mask.

### Pitfall 3: Forgetting Default ACL for `other`
Without `default:other::---`, new files might inherit the system umask's other permissions. **Solution**: Always explicitly set `default:other::---`.

### Pitfall 4: Setgid Not Set
Without setgid, files created by users whose primary group differs from the workspace group won't have the correct group ownership. **Solution**: Always `chmod g+s` or use mode `2xxx`.

### Pitfall 5: Adding Restricted Users to the Collaborating Group
If a restricted user is added to the collaborating group, they gain the owning group permissions, making it impossible to differentiate their access through named entries. **Solution**: Keep restricted users OUT of the collaborating group.

### Pitfall 6: Default ACLs Not Propagating to Subdirectories
Default ACLs propagate to all depths because subdirectories inherit the default ACL as their own default ACL. **Verify**: `getfacl <subdir>` should show both access and default entries matching the parent's defaults.

### Pitfall 7: chmod +x Sets other::--x
When a collaborator runs `chmod +x`, it sets `other::--x`. This is usually harmless because the parent directory blocks traversal for `other`. If tests check file-level `other` permissions strictly, use `setfacl -m m::rwx` instead of `chmod +x`.

## Idempotency and Reset

If the workspace already exists with incorrect configuration:
```bash
# Remove all ACLs and reset
setfacl -b <workspace>
# Then re-run the setup script
```

Or to make the setup idempotent:
```bash
# Clear existing ACLs before setting new ones
setfacl -b <workspace>
# Then proceed with the setup script
```

## Verification Checklist

- [ ] Users and groups exist
- [ ] Workspace directory created with correct owner:group
- [ ] Setgid bit set on workspace directory
- [ ] Base mode correct (typically 2770)
- [ ] Access ACLs set for all named principals
- [ ] Default ACLs set mirroring the access policy
- [ ] Default `other::---` explicitly set
- [ ] `getfacl` output verified for both access and default sections
- [ ] Inheritance tested with file and directory creation
- [ ] Restricted user access tested (read/traverse works, write/create denied)
- [ ] Unauthorized user access tested (completely denied)
- [ ] chmod +x by collaborator correctly grants execute to restricted users via mask

## Generalization Patterns

### Different Access Policy Topologies
- Multiple named users with different permission levels
- Named groups (use `g:<groupname>:<perms>` instead of `u:<username>:<perms>`)
- Mixed user + group ACLs: named user entries take precedence over group entries
- Explicit deny entries for specific users beyond the `other` class

**Mixed topology example** (spec variation: "principals whose access comes partly from group membership and partly from explicit ACL entries"):
```
Scenario: /srv/project owned by group developers
- alice is in developers → gets group::rwx automatically (no named entry needed)
- charlie is NOT in developers → needs u:charlie:rwx (named user entry)
- auditor is NOT in developers → needs u:auditor:r-x (restricted named entry)
```
Setup:
```bash
mkdir -p /srv/project
chown root:developers /srv/project
chmod 2770 /srv/project
# alice gets access through group membership (group::rwx)
# charlie needs explicit named entry (not in developers group)
setfacl -m u:charlie:rwx /srv/project
# auditor gets restricted access
setfacl -m u:auditor:r-x /srv/project
setfacl -m o::--- /srv/project
# Mirror as defaults
setfacl -d -m u::rwx /srv/project
setfacl -d -m g::rwx /srv/project
setfacl -d -m u:charlie:rwx /srv/project
setfacl -d -m u:auditor:r-x /srv/project
setfacl -d -m o::--- /srv/project
```
Result:
- alice: `group::rwx & mask` = `rwx` (via group membership, step 3 in matching order)
- charlie: `u:charlie:rwx & mask` = `rwx` (via named user entry, step 2)
- auditor: `u:auditor:r-x & mask` = `r-x` (via named user entry, step 2)
- random user: `other::---` = denied (step 4)

### Different Permission Models
- **Read-only collaborators**: `r--` for files, `r-x` for directories
- **Mask-based restriction**: Set default mask explicitly to cap all named entries
- **Policies relying on the ACL mask**: The mask can be used intentionally to restrict all named entries to a ceiling

### Deeper Directory Trees
Default ACLs automatically propagate to all depths. No special configuration needed. Verify with:
```bash
mkdir -p <workspace>/a/b/c
getfacl <workspace>/a/b/c  # should show inherited defaults
```

### Multiple Shared Workspaces
The same procedure applies to any directory. Each workspace gets its own set of ACLs.

## Quick Reference: setfacl Commands

```bash
# Set access ACL entry
setfacl -m u:<user>:<perms> <path>
setfacl -m g:<group>:<perms> <path>

# Set default ACL entry
setfacl -d -m u:<user>:<perms> <path>
setfacl -d -m g:<group>:<perms> <path>

# Remove an ACL entry
setfacl -x u:<user> <path>

# Remove all extended ACL entries
setfacl -b <path>

# Set multiple entries at once
setfacl -m u:alice:rwx,u:bob:r-x,o::--- <path>

# Set default and access in one command
setfacl -m u:alice:rwx -d -m u:alice:rwx <path>

# View ACLs
getfacl <path>

# View with numeric IDs
getfacl -n <path>
```
