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

## Quick Execution Reference

After extracting the policy (see Step 1), execute:

```bash
WS=<workspace_path>

# 1. Create clean workspace
rm -rf $WS && mkdir -p $WS
chown <owner>:<group> $WS && chmod <base_mode> $WS

# 2a. Set ACCESS ACLs
setfacl -m u::rwx,u:<collab1>:rwx,u:<collab2>:rwx,u:<limited>:r-x,g::rwx,m::rwx,o::--- $WS

# 2b. Set DEFAULT ACLs (for inheritance)
setfacl -m d:u::rwx,d:u:<collab1>:rwx,d:u:<collab2>:rwx,d:u:<limited>:r-x,d:g::rwx,d:m::rwx,d:o::--- $WS

# 3. Verify + clean
getfacl $WS
ls -la $WS/    # must be empty
```

**WARNING**: `setfacl -m` takes ONE comma-separated argument. Do NOT pass two comma-lists as separate arguments — the second will be misinterpreted as a filename. Use two `-m` calls (as shown above) or merge everything into a single contiguous string.

**Prerequisites before running**: verify `setfacl`/`getfacl` are installed and all referenced users/groups exist. If users or groups need creation:
```bash
groupadd <group>
useradd -m -G <group> <user>
```

## Detailed Procedure

### Step 1: Extract the Policy from the Task

**Do NOT copy any example verbatim.** Parse the task text into this structure:

```
workspace_path: <from task>
owning_group: <from task>
base_mode: <from task, e.g. 2770>
setgid: <yes if "new items keep the group" or mode starts with 2>

For each principal mentioned:
  principal_type: user | group | other
  principal_name: <name, or "other" for catch-all>
  access_on_directory: rwx | r-x | rw- | r-- | --- | etc.
  inherit_to_descendants: yes | no
```

**Permission mapping rules** (apply per principal based on task description):

| Task language | Directory ACL | Rationale |
|---|---|---|
| "full access", "read, write, execute" | `rwx` | All bits |
| "may traverse directories", "may execute scripts" | include `x` | x = traverse on dirs, execute on files |
| "may read files", "read ordinary shared files" | include `r` | r = read file contents, list directory |
| "must not create, delete, or modify" | exclude `w` | w on dir = create/delete entries |
| "must not create directories" | exclude `w` | Same — w on dir controls entry creation |
| "no access", "outside this policy" | `---` on `other` | Deny all |
| "read and write, no execute" | `rw-` | No traverse/execute |

**Critical rule**: A user who must traverse and read but NOT write/create/delete gets `r-x` on directories.

### Step 2: Prepare the Workspace (Idempotent)

Always start from a clean state:

```bash
rm -rf <workspace_path>
mkdir -p <workspace_path>
chown <owner>:<group> <workspace_path>
chmod <base_mode> <workspace_path>
```

If the directory must already exist (cannot be removed), reset ACLs first:
```bash
setfacl -b <workspace_path>
chmod <base_mode> <workspace_path>
chown <owner>:<group> <workspace_path>
```

### Step 3 & 4: Set ACLs (Access + Default in One Batch)

Use two batch calls — one for access, one for defaults. Each `-m` flag takes ONE comma-separated string:

```bash
WS=<workspace_path>

# Access ACLs (on the directory itself)
setfacl -m u::rwx,u:<name1>:<p1>,u:<name2>:<p2>,g::rwx,m::rwx,o::--- $WS

# Default ACLs (inherited by new children)
setfacl -m d:u::rwx,d:u:<name1>:<p1>,d:u:<name2>:<p2>,d:g::rwx,d:m::rwx,d:o::--- $WS
```

**Single-call alternative**: merge all entries into one argument:
```bash
setfacl -m u::rwx,u:<n1>:<p>,g::rwx,m::rwx,o::---,d:u::rwx,d:u:<n1>:<p>,d:g::rwx,d:m::rwx,d:o::--- $WS
```

**WARNING**: `setfacl -m` takes ONE argument. Never pass two comma-lists as separate positional args — the second will be misinterpreted as a path.

### Step 5: Verify and Clean

```bash
# Structural check
getfacl $WS
ls -ld $WS    # look for 's' in group column (setgid)

# Behavioral test (optional but recommended)
su -s /bin/bash -c 'echo test > $WS/tfile' <collaborator>
su -s /bin/bash -c 'cat $WS/tfile' <limited_user>         # expect: success
su -s /bin/bash -c 'echo x >> $WS/tfile' <limited_user>   # expect: Permission denied
su -s /bin/bash -c 'touch $WS/newfile' <limited_user>     # expect: Permission denied
su -s /bin/bash -c 'mkdir $WS/subdir' <collaborator>
getfacl $WS/subdir                                        # verify inheritance

# CLEAN UP all test artifacts — workspace must be empty for test harness
rm -rf $WS/tfile $WS/subdir
ls -la $WS/
```

**Do NOT leave test files.** Tests create their own content and may fail if unexpected files exist.

## Core Concepts

### POSIX ACL Entry Types

| Entry | Syntax | Scope |
|---|---|---|
| Owning user | `u::rwx` | Directory/file owner |
| Named user | `u:<name>:rwx` | One specific user |
| Owning group | `g::rwx` | Members of owning group |
| Named group | `g:<name>:rwx` | Members of one specific group |
| Mask | `m::rwx` | Ceiling for named users, named groups, owning group |
| Other | `o::---` | Everyone not matched above |

**Lookup order**: owning user → named user → owning/named group (best match) → other. Named user entries override group membership.

### Inheritance Mechanics

- **New subdirectories** inherit default ACLs as both access ACLs AND their own default ACLs (recursive).
- **New files** inherit default ACLs as access ACLs only.
- File creation mode ANDs with inherited permissions: regular files use mode `0666`, so inherited `x` bits are masked until `chmod +x`.

### setgid Bit

- `chmod g+s` (mode `2xxx`) → new files/subdirs inherit the parent's group ownership.
- Without setgid, new items get the creator's primary group.

### ACL Mask

- Maximum effective permission for named users, named groups, and owning group.
- Auto-recalculated by `setfacl` as union of group-class entries unless explicitly set.
- On new files, ANDed with creation mode (`rw-` typically).
- The mask does NOT affect the owning user (`u::`) or other (`o::`).

### umask Interaction

- The process umask does NOT interact with ACLs on directories that have default ACLs — default ACLs override umask for new children.
- However, umask CAN affect the initial `mkdir`/`chmod` if you don't explicitly set the mode afterward. Always use explicit `chmod` after `mkdir`.

## ACL Evaluation Order (Decision Algorithm)

```
1. If P is the owning user of F → use u:: entry
2. If P matches a named user entry u:<name>: → use that entry (AND with mask)
3. If P is in the owning group or matches a named group → use best group entry (AND with mask)
4. Otherwise → use o:: entry
```

Key implications:
- Named user entries override group membership (even if user is in owning group)
- `other` is a last resort, not an override
- Mask applies to steps 2 and 3 only

## Group-Based Access Patterns

**Owning group IS the collaborator group**: `g::rwx` covers all members. Add named user entries only for users needing different access than the group default.

**Named group separate from owning group**: Use `g:<name>:<perms>` entries for each additional group.

**User gets access through group AND has explicit entry**: Explicit named user entry takes precedence over any group entry.

## Mask as a Restriction Tool

The mask can intentionally restrict named entries:
```bash
setfacl -m u:editor:rwx,m::rw- $WS   # editor effective: rw-
```
Most tasks set `mask::rwx` to avoid unintentional restriction. Only restrict when the task requires it.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Named user can't access | Mask too restrictive | `setfacl -m m::rwx <path>` |
| New files have wrong group | setgid not set | `chmod g+s <path>` |
| New files don't inherit ACLs | Default ACLs missing | Add `d:` entries on parent |
| `setfacl: Operation not supported` | No ACL support | Remount with `acl` option |
| Limited user can still write | `w` on directory granted | Use `r-x` not `rwx` |
| Others can access | `other` not cleared | `setfacl -m o::--- <path>` |
| Old ACLs interfere | Not starting clean | `setfacl -b` or `rm -rf` first |
| Mask too low after add | Auto-recalculation | Explicitly `setfacl -m m::rwx` |
| Test fails with leftover files | Didn't clean up | `rm -rf` test files before finishing |
| `useradd`/`groupadd` not found | User doesn't exist | Create with `useradd -G <grp> <usr>` |
| Default ACLs not set, "No such file" | Two comma-lists passed as separate args to `-m` | Merge into one argument or use two `-m` calls |

## Self-Verification Checklist

1. [ ] `ls -ld <ws>`: correct owner, group, setgid (`s` in group column)
2. [ ] `getfacl <ws>`: all access entries match policy
3. [ ] `getfacl <ws>`: all default entries match policy (for inheritance)
4. [ ] `mask::rwx` (or intentional mask value)
5. [ ] `other::---` (no outside access, unless task allows)
6. [ ] Workspace is empty — no pre-created or leftover test files
7. [ ] Collaborator can create and share files
8. [ ] Limited user can read but not write or create
9. [ ] Outsider gets "Permission denied"
