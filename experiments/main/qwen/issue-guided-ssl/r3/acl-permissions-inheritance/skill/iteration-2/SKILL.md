---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux for shared workspaces with correct inheritance,
  mask-aware effective permissions, setgid group propagation, and per-principal
  access control. Handles arbitrary mixes of named users and groups, varied
  read/write/execute combinations, restricted principals (read/traverse-only),
  multi-generation directory trees, and creation-mode-dependent mask behavior.
---

# ACL Permissions Inheritance

## Overview

This skill configures POSIX ACLs on Linux directories so that:
- Named users and groups receive specified access levels
- Permissions propagate correctly to newly created files and subdirectories
- The ACL mask mechanism produces correct effective permissions automatically
- Setgid ensures group ownership propagates to descendants

## Core Mechanism: The Four-Layer ACL Model

POSIX ACLs operate through four interacting layers:

### 1. Access ACLs
Apply directly to the file/directory itself. Checked immediately when a process accesses the object.

### 2. Default ACLs
Stored only on directories. When a new child (file or subdirectory) is created inside the directory, the parent's default ACLs become the child's access ACLs. Subdirectories also inherit the default ACLs themselves, enabling multi-generation propagation.

### 3. The Mask Entry
The mask is the critical mechanism. It acts as a **bitwise AND ceiling** for all group-class entries:
- Named user entries (`u:username:perms`)
- Named group entries (`g:groupname:perms`)
- Owning group entry (`group::perms`)

Effective permissions = granted permissions AND mask.

### 4. ACL Evaluation Order
When a process accesses a file, the kernel checks permissions in strict order:
1. **Is the process the file owner?** → Use `user::` entry (mask NOT applied)
2. **Does a named user entry match?** → Use that `u:name:` entry, apply mask
3. **Does the owning group or a named group match?** → Use most permissive matching group entry, apply mask
4. **Otherwise** → Use `other::` entry (mask NOT applied)

This means a user who is both a named user AND a group member gets the named user entry (step 2), not the group entry. The mask always applies to steps 2 and 3 but never to steps 1 and 4.

**How the mask is determined on inherited children:**
- The default ACL's mask entry is ANDed with the creation mode's group permission bits
- Regular files created with mode `0666` (no execute) → mask becomes `rw-`
- Directories created with mode `0777` → mask stays `rwx`
- A file made executable via `chmod +x` → mask gains `x` bit

This is why a user granted `r-x` in the default ACL gets:
- `r--` effective on regular files (mask `rw-` strips execute)
- `r-x` effective on executable scripts (mask `rwx` preserves execute)
- `r-x` effective on directories (mask `rwx` preserves execute)

## Systematic Procedure

### Step 1: Directory Setup

```bash
# Create the directory
mkdir -p <path>

# Set ownership: user owner and group owner
chown <owner_user>:<owner_group> <path>

# Set base mode with setgid for group propagation
chmod <mode> <path>
# Typical: 2770 for full collaborator access, no others
# The '2' enables setgid — new items inherit the group
```

**Setgid is essential**: without it, new items get the creator's primary group instead of the shared group, breaking group-based access.

### Step 2: Access ACLs on the Directory

Set the access ACLs that control immediate access to the directory itself:

```bash
# Owning user (typically full access)
setfacl -m u::<owner_perms> <path>

# Named users with their granted permissions
setfacl -m u:<user1>:<perms> <path>
setfacl -m u:<user2>:<perms> <path>

# Named groups
setfacl -m g:<group>:<perms> <path>

# Owning group
setfacl -m g::<perms> <path>

# Others (typically no access for shared workspaces)
setfacl -m o::--- <path>
```

**Mask behavior**: When you add named entries, setfacl automatically recalculates the mask as the union of all group-class entries. If you need to restrict effective permissions below what was granted, set the mask explicitly:
```bash
setfacl -m m::<mask_perms> <path>
```

### Step 3: Default ACLs for Inheritance

Default ACLs determine what access ACLs newly created children will have:

```bash
# Set default entries — these propagate to new children
setfacl -d -m u::<perms> <path>       # default owning user
setfacl -d -m g::<perms> <path>       # default owning group
setfacl -d -m g:<group>:<perms> <path> # default named group
setfacl -d -m u:<user1>:<perms> <path> # default named user
setfacl -d -m u:<user2>:<perms> <path> # default named user
setfacl -d -m o::--- <path>            # default others (deny)
setfacl -d -m m::<mask_perms> <path>   # default mask
```

**Critical**: The default mask should typically be set to the maximum permissions any group-class entry needs. The creation mode will further restrict it for non-executable files.

### Step 4: Verification

Always verify with `getfacl`:

```bash
getfacl <path>
```

Check for:
- Both access and default entries present
- `flags: -s-` confirming setgid
- Mask value and any `#effective:` annotations
- `other::---` confirming no outside access

Test inheritance by creating test items and checking their ACLs:
```bash
# Create as a collaborator, check inherited ACLs
su -s /bin/bash <collaborator> -c "touch <path>/testfile"
getfacl <path>/testfile
# Verify mask is rw- for regular files, effective perms are correct
```

## Permission Design Patterns

### Full Collaborators
Grant `rwx` to users/groups who need complete access:
```bash
setfacl -m u:alice:rwx /path
setfacl -d -m u:alice:rwx /path
```

### Read-Only or Traverse-Only Principals
Grant `r-x` for users who should read files, traverse directories, and execute scripts but not modify anything:
```bash
setfacl -m u:runner:r-x /path
setfacl -d -m u:runner:r-x /path
```

The mask mechanism automatically handles the file vs. directory distinction:
- On regular files (mask `rw-`): effective = `r--` (read only)
- On directories (mask `rwx`): effective = `r-x` (traverse + list)
- On executable scripts (mask `rwx` after chmod +x): effective = `r-x`

### Explicit Denial
For principals that must be blocked entirely, use `---`:
```bash
setfacl -m u:blocked:--- /path
setfacl -d -m u:blocked:--- /path
```

Note: `other::---` handles the "everyone else" case. Named deny entries are needed only when specific users must be denied while others have access.

## Critical Mechanisms for Family Variants

### The chmod ↔ ACL Interaction

When `chmod` is called on a file with ACLs, it does NOT modify named user/group entries. Instead, it modifies exactly three entries:
- `user::` (owning user permissions)
- `mask::` (the group-class ceiling)
- `other::` (others permissions)

**Example**: `chmod +x script.sh` adds execute to user::, mask::, AND other::
- Before: `user::rw-, mask::rw-, other::---`
- After: `user::rwx, mask::rwx, other::--x`

This means `chmod +x` can inadvertently grant execute permission to `other`, potentially violating a "no outside access" policy. **The fix**: after `chmod`, explicitly reset other if needed:
```bash
chmod +x script.sh
setfacl -m o::--- script.sh  # restore the no-access policy for others
```

**Important**: `chmod g+...` modifies the mask, NOT the owning group entry. To change the owning group's permissions, use `setfacl -m g::...`.

### ACL Evaluation Order

POSIX ACLs are checked in a strict order when a process accesses a file:

1. **File owner?** → use `user::` entry (no mask applied)
2. **Named user entry matches?** → use that `u:username:` entry, **apply mask**
3. **Owning group or named group matches?** → use the most permissive matching group entry, **apply mask**
4. **Otherwise** → use `other::` entry (no mask applied)

**Key insight**: A user who matches BOTH a named user entry AND a group entry gets the **named user entry** (step 2), not the group entry. This matters when access comes "partly from group membership and partly from explicit ACL entries."

**Example**: alice is in the `editors` group (which has `r--`) but also has a named user entry `u:alice:rwx`. Alice gets `rwx` (masked), not `r--`.

### Named Group ACLs vs. Owning Group Entry

The owning group entry (`group::perms`) applies to members of the directory's owning group. Named group entries (`g:groupname:perms`) apply to members of that specific group.

**When to use named group ACLs**:
- When a group other than the owning group needs access
- When different groups need different permission levels
- When access must persist even if the owning group changes

**When the owning group entry suffices**:
- When all collaborators are in the owning group and need the same permissions
- Combined with setgid, this is often the simplest approach

**Best practice**: Set both the owning group default ACL and named group default ACLs for all groups that need access:
```bash
setfacl -d -m g::rwx /path           # owning group gets rwx
setfacl -d -m g:editors:rwx /path    # named group also gets rwx (redundant but explicit)
setfacl -d -m g:viewers:r-x /path    # different group gets different perms
```

### Sticky Bit for Shared-Write Directories

When multiple collaborators can create files in a shared directory, one user could delete another's files (if they have write permission on the directory). The **sticky bit** prevents this:

```bash
chmod +t /path  # or chmod 3770 instead of 2770
```

With the sticky bit set, only the file owner, directory owner, or root can delete/rename files. This is essential for "collaboration patterns where several actors must share a workspace."

**Scope**: The sticky bit is a traditional Unix special permission bit, completely separate from POSIX ACLs. It applies **only to the specific directory** it is set on — it is **NOT inherited** by subdirectories through ACLs or any other mechanism. Default ACLs propagate only ACL entries (user, group, mask, other), not special bits.

**For multi-level shared-write trees**: Each directory that needs deletion protection must have `chmod +t` applied explicitly. Options:
- Apply after creating each subdirectory: `mkdir subdir && chmod +t subdir`
- Post-hoc for existing trees: `find <path> -type d -exec chmod +t {} +`
- If the task only requires protection at the top-level workspace, set it only there and note the scope limitation.

## Common Pitfalls

1. **Forgetting setgid**: New files get wrong group, breaking group-based ACL access
2. **Forgetting default ACLs**: Children get no inherited ACLs, only base permissions
3. **Forgetting default `other::---`**: Children may be world-accessible
4. **Mask too restrictive**: Named entries appear granted but effective permissions are lower — always check `getfacl` output for `#effective:` annotations
5. **Default mask not set**: May default to something unexpected; always set it explicitly
6. **Not accounting for creation mode**: Regular files never get execute via inheritance alone — the mask strips it. Scripts must be explicitly `chmod +x`'d.
7. **chmod +x breaking other:: policy**: `chmod +x` adds execute to other::, potentially allowing outsiders to execute. Always reset other:: after chmod if needed.
8. **Confusing chmod g+... with group entry**: `chmod g+...` modifies the mask, not the owning group entry. Use `setfacl -m g::...` for the owning group.
9. **Forgetting sticky bit in shared-write scenarios**: Without it, collaborators can delete each other's files.

## Parameterization Guide

The following vary across tasks in this family:

| Parameter | What changes | Example values |
|-----------|-------------|----------------|
| Directory path | Where the workspace lives | `/srv/shared`, `/workspace/project` |
| Owner user/group | Who owns the directory | `root:editors`, `admin:devteam` |
| Base mode | Permission bits + setgid | `2770`, `2750` |
| Collaborators | Users/groups with full access | `alice:rwx`, `devteam:rwx` |
| Restricted users | Users with limited access | `runner:r-x`, `viewer:r--` |
| Denied users | Users explicitly blocked | `intern:---` |
| Others policy | World access level | `---`, `r-x` |

The mechanism (mask, default ACL inheritance, setgid) is invariant.
