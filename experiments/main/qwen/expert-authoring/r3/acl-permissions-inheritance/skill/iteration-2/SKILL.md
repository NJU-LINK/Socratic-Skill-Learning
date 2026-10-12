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

**Lookup order**: owning user → named user → owning group or named group (best match) → other. Once a principal matches a named entry or the owning group, the `other` entry does NOT apply.

### Inheritance via Default ACLs

- Default ACLs (set with `-d` flag or `d:` prefix) apply only to directories.
- **New subdirectories** inherit default ACLs as both their access ACLs AND their own default ACLs (recursive).
- **New files** inherit default ACLs as access ACLs only (files cannot have default ACLs).
- File creation mode ANDs with inherited permissions: regular files created with mode `0666`, so inherited `x` bits are masked until `chmod +x` is applied.

### setgid Bit

- `chmod g+s` (or mode `2xxx`) on a directory → new files/subdirs inherit the parent's group ownership.
- Without setgid, new items get the creator's primary group.

### ACL Mask

- Maximum effective permission for: named users, named groups, owning group.
- `setfacl` auto-recalculates mask as union of group-class entries unless explicitly set.
- On new files, mask is ANDed with creation mode (`rw-` for regular files).

## Procedure

### Step 1: Extract the Policy from the Task

**Do NOT copy any example verbatim.** Parse the actual task text into this structure:

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

**Permission mapping rules** (apply to each principal based on task description):

| Task language | Directory ACL | Rationale |
|---|---|---|
| "full access", "read, write, execute" | `rwx` | All bits |
| "may traverse directories", "may execute scripts" | include `x` | x = traverse on dirs, execute on files |
| "may read files", "read ordinary shared files" | include `r` | r = read file contents, list directory |
| "must not create, delete, or modify" | exclude `w` on dir | w on dir = create/delete entries |
| "must not create directories" | exclude `w` on dir | Same mechanism |
| "no access", "outside this policy" | `---` on `other` | Deny all |
| "read and write, no execute" | `rw-` | No traverse/execute |

**Critical**: A limited-access user who needs to traverse and read but not write gets `r-x` on directories. The `x` enables traversal; absence of `w` prevents creating/deleting entries.

### Step 2: Prepare the Workspace (Idempotent)

**Always start from a clean state.** If the directory might already exist with unknown ACLs, remove and recreate:

```bash
# Remove existing directory and contents for clean slate
rm -rf <workspace_path>

# Create fresh
mkdir -p <workspace_path>
chown <owner>:<group> <workspace_path>
chmod <base_mode> <workspace_path>
```

If the task specifies the directory must already exist, skip removal but explicitly reset:
```bash
setfacl -b <workspace_path>   # remove all ACLs first
chmod <base_mode> <workspace_path>
chown <owner>:<group> <workspace_path>
```

### Step 3: Set Access ACLs

Apply the policy extracted in Step 1:

```bash
WS=<workspace_path>

# For each named user in the policy:
setfacl -m u:<name>:<perms> $WS

# For each named group beyond the owning group:
setfacl -m g:<name>:<perms> $WS

# Deny others (almost always required):
setfacl -m o::--- $WS

# Ensure mask allows intended maximum:
setfacl -m m::rwx $WS
```

### Step 4: Set Default ACLs for Inheritance

Default ACLs determine what newly created children inherit. They should mirror the access ACLs unless the task specifies different inheritance behavior:

```bash
# For each named user:
setfacl -d -m u:<name>:<perms> $WS

# For each named group:
setfacl -d -m g:<name>:<perms> $WS

# Owning group default:
setfacl -d -m g::<perms> $WS

# Others default (usually ---):
setfacl -d -m o::--- $WS

# Default owning user:
setfacl -d -m u::rwx $WS

# Default mask:
setfacl -d -m m::rwx $WS
```

**Batch alternative** (all entries in one call):
```bash
setfacl -m d:u::rwx,d:u:<name1>:<p>,d:u:<name2>:<p>,d:g::rwx,d:o::---,d:m::rwx $WS
```

### Step 5: Verify

```bash
# 1. Structural check
ls -ld $WS                    # owner, group, setgid (s in group execute)
getfacl $WS                   # all access + default entries
stat -c "%A %U %G" $WS       # permissions string, owner, group

# 2. Behavioral test (recommended before declaring done)
#    Create test artifacts, verify access, then CLEAN UP
su -s /bin/bash -c 'echo test > $WS/tfile' <collaborator> 2>&1
su -s /bin/bash -c 'cat $WS/tfile' <limited_user> 2>&1      # should succeed
su -s /bin/bash -c 'echo x >> $WS/tfile' <limited_user> 2>&1 # should fail
su -s /bin/bash -c 'touch $WS/newfile' <limited_user> 2>&1   # should fail
su -s /bin/bash -c 'ls $WS' <outsider> 2>&1                  # should fail
su -s /bin/bash -c 'mkdir $WS/subdir' <collaborator> 2>&1    # should succeed
getfacl $WS/subdir                                            # verify inheritance

# 3. CLEAN UP all test artifacts
rm -rf $WS/tfile $WS/subdir
ls -la $WS/   # confirm empty
```

**Do NOT leave test files in the workspace.** Tests create their own content and may fail if unexpected files are present.

## ACL Evaluation Order (Decision Algorithm)

When Linux checks whether principal P can access file F:

```
1. If P is the owning user of F → use u:: entry
2. If P matches a named user entry u:<name>: → use that entry (AND with mask)
3. If P is in the owning group or matches a named group → use best group entry (AND with mask)
4. Otherwise → use o:: entry
```

This means:
- Named user entries override group membership (even if the user is in the owning group)
- The `other` entry is a last resort, not an override
- The mask applies to steps 2 and 3 but NOT to step 1 (owning user) or step 4 (other)

## Group-Based Access Patterns

When a task specifies access through group membership:

**Pattern: Owning group IS the collaborator group**
```bash
# Group is set as owning group via chown and setgid
# g::rwx in both access and default ACLs covers all members
# Add named user entries only for users who need DIFFERENT access than the group default
```

**Pattern: Named group separate from owning group**
```bash
# When a different group needs specific access:
setfacl -m g:contractors:r-x $WS
setfacl -d -m g:contractors:r-x $WS
# Members of contractors get r-x even though they're not in the owning group
```

**Pattern: User gets access through group AND has explicit entry**
```bash
# Explicit named user entry takes precedence over any group entry
# Use this when one group member needs different access than other members
```

## Mask as a Restriction Tool

The mask can intentionally restrict named entries:

```bash
# Set permissive named entries but restrictive mask:
setfacl -m u:editor:rwx $WS
setfacl -m m::rw- $WS
# editor's effective permissions: rw- (x masked out)
# Useful when task requires "editor can do everything except execute"
```

Most tasks set `mask::rwx` to avoid unintentional restriction. Only use a restrictive mask when the task explicitly requires it.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Named user can't access | Mask too restrictive | `setfacl -m m::rwx <path>` |
| New files have wrong group | setgid not set | `chmod g+s <path>` |
| New files don't inherit ACLs | Default ACLs missing | Add `d:` entries on parent |
| `setfacl: Operation not supported` | No ACL support | Remount with `acl` option |
| Limited user can still write | `w` on directory granted | Use `r-x` not `rwx` |
| Others can access | `other` not cleared | `setfacl -m o::--- <path>` |
| Old ACLs interfere | Not starting clean | `setfacl -b <path>` or `rm -rf` first |
| New entry not taking effect | Auto-recalculated mask too low | Explicitly `setfacl -m m::rwx` |
| Test fails with leftover files | Didn't clean up test artifacts | `rm -rf` test files before finishing |

## Self-Verification Checklist

1. [ ] `ls -ld <ws>`: correct owner, group, setgid (`s` in group column)
2. [ ] `getfacl <ws>`: all access entries match policy
3. [ ] `getfacl <ws>`: all default entries match policy (for inheritance)
4. [ ] `mask::rwx` (or intentional mask value)
5. [ ] `other::---` (no outside access, unless task allows it)
6. [ ] Workspace is empty — no pre-created or leftover test files
7. [ ] Behavioral test: collaborator can create and share files
8. [ ] Behavioral test: limited user can read but not write or create
9. [ ] Behavioral test: outsider gets "Permission denied"
