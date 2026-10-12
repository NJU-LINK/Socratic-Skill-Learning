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

## Core Mechanism: The Three-Layer ACL Model

POSIX ACLs operate through three interacting layers:

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

## Common Pitfalls

1. **Forgetting setgid**: New files get wrong group, breaking group-based ACL access
2. **Forgetting default ACLs**: Children get no inherited ACLs, only base permissions
3. **Forgetting default `other::---`**: Children may be world-accessible
4. **Mask too restrictive**: Named entries appear granted but effective permissions are lower — always check `getfacl` output for `#effective:` annotations
5. **Default mask not set**: May default to something unexpected; always set it explicitly
6. **Not accounting for creation mode**: Regular files never get execute via inheritance alone — the mask strips it. Scripts must be explicitly `chmod +x`'d.

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
