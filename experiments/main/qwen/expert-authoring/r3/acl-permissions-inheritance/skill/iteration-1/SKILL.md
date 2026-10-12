---
name: acl-permissions-inheritance
description: >
  Configure Linux POSIX ACLs for shared workspaces with correct ownership,
  setgid group propagation, access ACLs for named principals, and default ACLs
  for permission inheritance to newly created descendants.
---

# ACL Permissions & Inheritance for Shared Workspaces

## When to Apply

Use this skill when a task asks you to:
- Configure a shared directory with Linux ACLs (`setfacl` / `getfacl`)
- Grant different permission levels to specific users or groups
- Ensure permissions propagate (inherit) to new files and subdirectories
- Set up setgid for group ownership propagation
- Restrict or deny access for users outside the policy

## Prerequisites

- The `acl` package must be installed (`setfacl`, `getfacl` available)
- Root or sudo access to create directories and set ACLs
- Users and groups referenced in the policy must already exist

## Core Concepts

### POSIX ACL Entry Types

| Entry | Syntax | Purpose |
|---|---|---|
| Owning user | `u::rwx` | Directory owner's permissions |
| Named user | `u:alice:rwx` | Specific user's permissions |
| Owning group | `g::rwx` | Owning group's permissions |
| Named group | `g:editors:rwx` | Specific group's permissions |
| Mask | `m::rwx` | Ceiling for named users, named groups, and owning group |
| Other | `o::---` | Everyone not covered above |

### Inheritance via Default ACLs

- Default ACLs (prefix `d:` or set with `-d`) are inherited by **newly created** children.
- New **subdirectories** inherit default ACLs as both their access AND default ACLs (recursive propagation).
- New **files** inherit default ACLs as access ACLs, but the effective permissions are ANDed with the file creation mode (typically `0666` for regular files, so execute is absent unless explicitly set via `chmod +x`).

### setgid Bit

- Setting the setgid bit (`chmod g+s` or mode `2xxx`) on a directory causes new files and subdirectories to inherit the parent's **group ownership**.
- Without setgid, new items get the creator's primary group.

### ACL Mask

- The mask is the **maximum effective permission** for: named users, named groups, and the owning group.
- The mask is automatically recalculated by `setfacl` to be the union of all group-class entries unless explicitly set.
- On newly created files, the mask is ANDed with the creation mode (so it's typically `rw-` for non-executable files).

## General Procedure

### Step 1: Identify the Policy from the Task

Parse the task requirements into a structured policy:

```
workspace_path: /srv/shared (or whatever the task specifies)
owning_group: <group> (e.g., editors)
setgid: yes/no (usually yes for shared workspaces)
base_mode: e.g., 2770 (owner rwx, group rwx, other ---, setgid)

principals:
  - name: alice
    type: user
    access: rwx        # full access
    inherit: true      # permissions carry to descendants
  - name: bob
    type: user
    access: rwx
    inherit: true
  - name: runner
    type: user
    access: r-x        # read + traverse, no write
    inherit: true
  - name: <outside users>
    type: other
    access: ---        # no access at all
```

**Key decision points:**
- "full access" / "read, write, execute" → `rwx`
- "read only" / "may read but not modify" → `r--` for files, `r-x` for directories (need x to traverse)
- "read and traverse, no create/delete/modify" → `r-x` (write on directory controls create/delete)
- "no access" → `---`
- "may execute scripts that collaborators make executable" → include `x` in the ACL; the execute bit on files is only effective when the file is explicitly made executable

### Step 2: Create the Workspace Directory

```bash
# Create directory
mkdir -p <workspace_path>

# Set ownership: root (or specified user) and the designated group
chown root:<group> <workspace_path>

# Set base mode with setgid
chmod 2770 <workspace_path>
# 2 = setgid, 770 = rwx for owner and group, --- for other
# Adjust if the task specifies a different base mode
```

### Step 3: Set Access ACLs on the Workspace

These control access to the directory itself.

```bash
# Named users with full access
setfacl -m u:<user1>:rwx <workspace_path>
setfacl -m u:<user2>:rwx <workspace_path>

# Named users with limited access (e.g., read+traverse only)
setfacl -m u:<limited_user>:r-x <workspace_path>

# Named groups (if needed beyond the owning group)
setfacl -m g:<group>:rwx <workspace_path>

# Deny others
setfacl -m o::--- <workspace_path>
```

**Important:** After adding named entries, verify the mask is correct. `setfacl` auto-recalculates the mask as the union of all group-class entries. If you need a specific mask:
```bash
setfacl -m m::rwx <workspace_path>
```

### Step 4: Set Default ACLs for Inheritance

These propagate to newly created files and subdirectories.

```bash
# Default ACLs mirror the access ACLs for inheritance
setfacl -d -m u:<user1>:rwx <workspace_path>
setfacl -d -m u:<user2>:rwx <workspace_path>
setfacl -d -m u:<limited_user>:r-x <workspace_path>
setfacl -d -m g::<rwx> <workspace_path>        # owning group default
setfacl -d -m o::--- <workspace_path>           # others denied by default

# If using named groups:
setfacl -d -m g:<group>:rwx <workspace_path>
```

**Alternatively**, use the `d:` prefix in a single `-m` call:
```bash
setfacl -m d:u:alice:rwx,d:u:bob:rwx,d:u:runner:r-x,d:g::rwx,d:o::--- <workspace_path>
```

### Step 5: Verify the Configuration

```bash
# Check the workspace ACLs
getfacl <workspace_path>

# Expected structure for a full-access + limited-access policy:
# user::rwx
# user:alice:rwx
# user:bob:rwx
# user:runner:r-x
# group::rwx
# mask::rwx
# other::---
# default:user::rwx
# default:user:alice:rwx
# default:user:bob:rwx
# default:user:runner:r-x
# default:group::rwx
# default:mask::rwx
# default:other::---
```

Verify key properties:
- [ ] `flags: -s-` (setgid is set)
- [ ] `mask::rwx` (or appropriate ceiling)
- [ ] `other::---` (no outside access)
- [ ] All named user/group entries appear in both access and default sections
- [ ] Group ownership is correct (`chown` was applied)

## How Inheritance Works in Practice

### New Subdirectories
- Inherit **all** default ACL entries as both access and default ACLs
- setgid ensures group ownership propagates
- The mask is `rwx` → all entries are fully effective
- Result: identical ACL structure to the parent

### New Regular Files
- Inherit default ACL entries as access ACLs (no default ACLs on files)
- setgid ensures group ownership propagates
- The mask is typically `rw-` (because files are created with mode `0666`)
- Effective permissions are ANDed with the mask:
  - `rwx` entries become `rw-` effective (full read/write, no execute)
  - `r-x` entries become `r--` effective (read only, no execute)
- When a file is later made executable (`chmod +x`), the mask becomes `rwx`:
  - `rwx` entries become fully effective
  - `r-x` entries become `r-x` effective (can now execute)

### Why Write Permission on Directories Matters
- Write (`w`) on a directory = ability to create/delete entries within it
- Execute (`x`) on a directory = ability to traverse (cd into, access known files)
- A user with `r-x` on the directory can list and access files but cannot create/delete
- A user with `rwx` on the directory can create/delete files

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Named user can't access despite ACL entry | Mask is too restrictive | `setfacl -m m::rwx <path>` |
| New files have wrong group | setgid not set | `chmod g+s <path>` |
| New files don't inherit ACLs | Default ACLs not set | Set `d:` entries on parent |
| `setfacl: Operation not supported` | Filesystem lacks ACL support | Remount with `acl` option |
| Runner can still write | Write on directory granted | Ensure limited user has `r-x` not `rwx` on directory |
| Others can access | `other` entry not cleared | `setfacl -m o::--- <path>` |
| `chmod +x` on file gives others execute | chmod affects `other::` ACL entry | Directory-level `other::---` blocks access regardless |

## Common Patterns

### Pattern: Full Collaborators + Read-Only Observer
```bash
# Collaborators: full rwx on everything
setfacl -m u:collab1:rwx,u:collab2:rwx /workspace
setfacl -d -m u:collab1:rwx,u:collab2:rwx /workspace

# Observer: read + traverse only
setfacl -m u:observer:r-x /workspace
setfacl -d -m u:observer:r-x /workspace
```

### Pattern: Group-Based Access
```bash
# Group gets full access
setfacl -m g:team:rwx /workspace
setfacl -d -m g:team:rwx /workspace

# Individual from another group gets limited access
setfacl -m u:contractor:r-x /workspace
setfacl -d -m u:contractor:r-x /workspace
```

### Pattern: Multiple Permission Tiers
```bash
# Admin: full access
setfacl -m u:admin:rwx /workspace
setfacl -d -m u:admin:rwx /workspace

# Editor: read+write, no execute on directory (can still execute files)
setfacl -m u:editor:rwx /workspace
setfacl -d -m u:editor:rwx /workspace

# Viewer: read-only
setfacl -m u:viewer:r-x /workspace
setfacl -d -m u:viewer:r-x /workspace
```

## Self-Verification Checklist

After configuring ACLs, always run through this checklist:

1. **Directory structure**: `ls -ld <workspace>` shows correct owner, group, setgid, and mode
2. **Access ACLs**: `getfacl <workspace>` shows all required entries
3. **Default ACLs**: `getfacl <workspace>` shows matching default entries for inheritance
4. **Mask**: mask entry allows the intended maximum permissions
5. **Other**: `other::---` denies unauthorized access
6. **Functional test** (if possible before submission):
   - Create a file as a collaborator → other collaborator can modify it
   - Limited user can read but not write
   - Outside user gets "Permission denied"
