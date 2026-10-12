---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspace directories with correct
  permission inheritance for diverse access policies. Covers named user/group
  ACL entries, default ACLs for propagation to new files and subdirectories,
  ACL mask management, setgid-based group ownership inheritance, and
  differential permission models (full collaborators vs read-only traversers
  vs denied outsiders). Generalizes to arbitrary topologies of principals,
  permission combinations, and inheritance depths.
---

# ACL Permissions Inheritance

## Overview

This skill configures Linux POSIX ACLs on shared workspace directories so that
permissions propagate correctly to newly created files and subdirectories. The
core challenge is combining three permission mechanisms — base Unix modes,
POSIX ACL entries, and default ACLs — into a coherent policy that survives
arbitrary file creation by any authorized principal.

## Core Concepts

### Three Layers of Permission Control

1. **Base Unix mode** (owner/group/other + setuid/setgid/sticky): Provides
   the owning user entry, owning group entry, and the "other" class. The
   setgid bit on a directory forces new files/subdirectories to inherit the
   directory's group ownership.

2. **Access ACL entries**: Named user (`user:name:perms`) and named group
   (`group:name:perms`) entries that extend beyond the traditional three-class
   model. These control access to the directory itself.

3. **Default ACL entries**: Templates (`default:...`) stored on directories
   that are copied (intersected with the creation mode) to become the access
   ACLs of newly created children. Only directories can have default ACLs.

### The Mask and Effective Permissions

The ACL mask entry (`mask::perms`) caps the effective permissions for:
- All named user entries
- All named group entries  
- The owning group entry

The mask does NOT affect the owning user (`user::`) or other (`other::`).

**Critical**: When default ACLs are present, the file creation mode (from the
`open`/`mkdir` syscall) is intersected with each default ACL entry to produce
the child's access ACL. This means:
- Regular files (created with mode 0666): no execute bit in mask or entries
- Directories and executables (created with mode 0777): execute bit preserved

### How Inheritance Works

When a new file or directory is created inside a parent with default ACLs:

```
child_access_acl_entry = default_acl_entry AND file_creation_mode
```

For a regular file (creation mode 0666 = rw-rw-rw-):
- `default:user:alice:rwx` → `user:alice:rw-` (x stripped)
- `default:user:runner:r-x` → `user:runner:r--` (x stripped)
- `default:mask::rwx` → `mask::rw-` (x stripped)

For a directory (creation mode 0777 = rwxrwxrwx):
- All entries pass through unchanged
- Default ACLs are also copied to the child directory (enabling deeper inheritance)

## General Method

### Step 1: Analyze the Access Policy

Identify all principals and classify them:

| Role | Typical Permissions on Dirs | Typical Permissions on Files |
|------|---------------------------|------------------------------|
| Full collaborator | rwx | rwx (effective rw- on non-exec, rwx on exec) |
| Read/traverse only | r-x | r-x (effective r-- on non-exec, r-x on exec) |
| Read-only (no traverse) | r-- | r-- |
| Denied | --- | --- |

Key insight: You set ONE ACL entry per principal that applies to both files
and directories. The file creation mode naturally differentiates: execute
permission only becomes effective on files explicitly made executable and on
directories.

### Step 2: Create the Directory with Correct Base Properties

```bash
mkdir -p <path>
chown <owner>:<group> <path>
chmod <setgid_mode> <path>
```

The setgid mode is `2000 | base_mode`. Common choices:
- `2770` = setgid + rwxrwx--- (collaborators only, no outsiders)
- `2775` = setgid + rwxrwxr-x (collaborators + read-only others)
- `2750` = setgid + rwxr-x--- (owner full, group read/traverse)

**Setgid is essential** for group propagation: it ensures all new items
inherit the directory's group, making group-based ACL entries and group
ownership consistent throughout the tree.

### Step 3: Set Access ACLs on the Directory

For each principal in the policy:

```bash
# Named users
setfacl -m u:<username>:<perms> <path>

# Named groups  
setfacl -m g:<groupname>:<perms> <path>

# Other (outsiders)
setfacl -m o::--- <path>
```

The mask is auto-calculated by setfacl as the union of all named entries and
the owning group. Verify it allows the maximum permissions needed:

```bash
getfacl <path>
# Check mask:: includes all needed permission bits
```

If the mask is too restrictive, set it explicitly:
```bash
setfacl -m m::<perms> <path>
```

### Step 4: Set Default ACLs for Inheritance

Mirror the access ACL structure as default entries:

```bash
# Owner of new files
setfacl -d -m u::<owner_perms> <path>

# Owning group of new files
setfacl -d -m g::<group_perms> <path>

# Named users (same perms as access ACL)
setfacl -d -m u:<username>:<perms> <path>

# Named groups
setfacl -d -m g:<groupname>:<perms> <path>

# Mask - must allow maximum needed permissions
setfacl -d -m m::<max_perms> <path>

# Other
setfacl -d -m o::--- <path>
```

**Critical rules for default ACLs:**
- The default mask must be at least as permissive as the most-privileged
  named entry, or effective permissions will be capped.
- Default `user::` controls the owner permissions of new files.
- Default `group::` controls the owning group permissions of new files.
- Default `other::` controls outsider access to new files.

### Step 5: Verify the Configuration

```bash
# Check the directory's full ACL
getfacl <path>

# Test inheritance by creating test items
su -s /bin/sh <creator> -c "touch <path>/testfile"
su -s /bin/sh <creator> -c "mkdir <path>/testdir"
getfacl <path>/testfile
getfacl <path>/testdir

# Test actual access for each principal
su -s /bin/sh <user> -c "cat <path>/testfile"       # read
su -s /bin/sh <user> -c "echo x >> <path>/testfile" # write
su -s /bin/sh <user> -c "ls <path>/"                 # traverse
su -s /bin/sh <user> -c "touch <path>/newfile"       # create
```

Clean up test items after verification.

## Common Patterns and Variations

### Pattern: Collaborators + Read-Only Traverser + Denied Others

The canonical pattern (used in the seed task):
- Collaborators get `rwx` (full access)
- Traverser gets `r-x` (read + traverse + execute scripts)
- Others get `---` (no access)
- Default ACLs mirror access ACLs
- Setgid ensures group propagation

### Pattern: Multiple Groups with Different Access Levels

When different groups need different access:
```bash
setfacl -m g:developers:rwx <path>
setfacl -m g:reviewers:r-x <path>
setfacl -d -m g:developers:rwx <path>
setfacl -d -m g:reviewers:r-x <path>
```

### Pattern: Explicit Denial for Specific Principals

POSIX ACLs don't have explicit "deny" entries like Windows ACLs. To deny
a specific user, simply don't grant them any named entry and ensure `other`
is `---`. If they're in a group that has access, you can add a named user
entry with `---`:
```bash
setfacl -m u:blocked_user:--- <path>
setfacl -d -m u:blocked_user:--- <path>
```
Note: Named user entries take precedence over group entries in POSIX ACL
evaluation, so this effectively blocks the user even if their group has access.

### Pattern: Mask-Restricted Effective Permissions

When you want named entries to grant certain bits but the mask limits them:
```bash
setfacl -m u:alice:rwx <path>
setfacl -m m::r-x <path>   # alice effective: r-x despite rwx entry
```
This is useful for temporarily restricting access without removing entries.
For default ACLs, setting `default:mask::r-x` would cap all new files' named
entries to r-x effective.

### Pattern: Deep Directory Trees

Default ACLs propagate recursively — each new subdirectory inherits the
parent's default ACLs as both its access ACLs AND its own default ACLs.
This means a single set of default ACLs on the root workspace directory
correctly governs the entire tree, regardless of depth.

## Troubleshooting

### Problem: Named user can't access despite correct ACL entry
- **Check the mask**: `getfacl` shows effective permissions after `#effective:`
- If mask is too restrictive, effective perms are capped

### Problem: New files don't inherit expected ACLs
- **Verify default ACLs exist** on the parent: `getfacl <parent>`
- **Check creation mode**: Files opened without execute intent get 0666,
  stripping x bits from inherited entries

### Problem: Group ownership not propagating
- **Verify setgid bit**: `ls -ld <dir>` should show `s` in group execute
- **Check filesystem**: ACLs require ext3/ext4/xfs/btrfs with ACL support

### Problem: User in group still can't access
- **ACL evaluation order**: owner → named users → (owning group OR named
  groups, masked) → other. If a named user entry exists, group entries
  are skipped for that user.
- **Named user `---` overrides group**: A named user entry of `---` blocks
  access even if the user's group has permissions.

### Problem: User can't read files despite file ACL granting read
- **Check directory execute bits**: The `x` bit on directories grants
  search/traverse permission, which is required to access any inode within.
  Without `x` on every ancestor directory, the kernel denies access before
  evaluating the file's ACL.
- **Directory permission semantics**:
  - `r--` on directory = can list names but cannot access any file inside
  - `--x` on directory = can traverse if you know the filename, but cannot list
  - `r-x` on directory = can list AND traverse (minimum for "read files inside")
- **Fix**: Ensure every directory in the path has at least `--x` for the user.

### Problem: Stale numeric UID entries after user deletion
- When a user is deleted, ACL entries persist by UID (e.g., `user:1004:rwx`)
- The entry remains even though the username no longer resolves
- **Fix**: Remove stale entries with `setfacl -x u:<uid> <path>`
- For recursive cleanup: `setfacl -R -x u:<uid> <path>`
- **Prevention**: Clean up ACLs before deleting users, or audit after deletion

## chmod and ACL Interaction (Critical)

When files have ACLs, `chmod` behaves differently than traditional Unix permissions.

### How chmod Modifies ACL Entries

With ACLs present, `chmod` modifies exactly three entries:
- `user::` (owner permissions)
- `mask::` (the ACL mask, NOT the owning group entry)
- `other::` (other permissions)

It does NOT touch named user/group entries (`user:name:` or `group:name:`).

### Security Implications

**Example**: A file created with default ACLs has:
```
user::rw-
user:alice:rwx  #effective:rw-
user:runner:r-x #effective:r--
mask::rw-
other::---
```

If a collaborator runs `chmod 755 file`:
```
user::rwx
user:alice:rwx  #effective:r-x  ← mask reduced to r-x
user:runner:r-x #effective:r-x  ← mask reduced to r-x
mask::r-x                       ← CHANGED from rw-
other::r-x                      ← CHANGED from --- (SECURITY ISSUE!)
```

**Problems**:
1. Named users lose write access on that file (mask dropped to r-x)
2. Outsiders gain read+execute access (other changed to r-x)
3. The security policy is violated for that file

**Important**: This affects only the specific file. Directory ACLs remain unchanged, so collaborators retain full workspace access (create/delete/traverse). The write loss is file-scoped, not workspace-scoped.

### chmod +x vs chmod 755

- `chmod 755` sets `mask::r-x` and `other::r-x`
- `chmod +x` (equivalent to `a+x`) sets `mask::` to include `x` and `other::` to include `x`, yielding `other::--x` (outsiders can execute but not read)

Both violate the `other::---` security policy.

### Safe Pattern: Making Scripts Executable

To make a script executable while preserving ACL security:

```bash
# WRONG: chmod 755 file (changes mask and other)
# WRONG: chmod +x file (changes mask and other)

# RIGHT: Use setfacl to set mask and owner execute
setfacl -m u::rwx,m::rwx file
```

This sets:
- `user::rwx` (owner can execute)
- `mask::rwx` (named users can execute, if their entry includes x)
- Leaves `other::` unchanged (stays `---`)

### Best Practices

1. **Never use numeric chmod** (e.g., `chmod 755`) on files with ACLs
2. **Avoid symbolic chmod** (e.g., `chmod +x`) on files with ACLs
3. **Use setfacl** to modify permissions on ACL-enabled files
4. **Document** that collaborators should use `setfacl` instead of `chmod`
5. **Train users** that the security policy depends on correct ACL management

## Recursive ACL Operations (Modifying Existing Trees)

Default ACLs only apply to **newly created** children, not existing items. When you need to add or modify a principal's access across an existing directory tree, you must update both access ACLs and default ACLs separately.

### Adding a Principal to an Existing Tree

**Scenario**: A new collaborator `charlie` needs access to an existing workspace with subdirectories and files.

```bash
# Step 1: Add to workspace root (access + default)
setfacl -m u:charlie:rwx /srv/shared
setfacl -d -m u:charlie:rwx /srv/shared

# Step 2: Add access ACLs recursively to existing items
setfacl -R -m u:charlie:rwx /srv/shared

# Step 3: Add default ACLs to existing directories (for future children)
find /srv/shared -type d -exec setfacl -d -m u:charlie:rwx {} \;
```

**Why three steps?**
- Step 1 ensures new items created directly in `/srv/shared` inherit charlie's access
- Step 2 grants charlie access to existing files and directories
- Step 3 ensures charlie gets access to new items created in existing subdirectories

### Removing a Principal from an Existing Tree

```bash
# Remove access ACLs recursively
setfacl -R -x u:charlie /srv/shared

# Remove default ACLs from existing directories
find /srv/shared -type d -exec setfacl -d -x u:charlie {} \;
```

### Modifying Permissions Recursively

```bash
# Change runner from r-x to r-- (read-only, no traverse)
setfacl -R -m u:runner:r-- /srv/shared
find /srv/shared -type d -exec setfacl -d -m u:runner:r-- {} \;
```

**Important**: Changing directory permissions from `r-x` to `r--` prevents traversal. Users can list directory contents but cannot access any file inside, even if the file's ACL grants read.

### Key Insight

The pattern is always:
1. `setfacl -R -m` for access ACLs on all existing items
2. `find -type d -exec setfacl -d -m` for default ACLs on existing directories

This ensures both immediate access and future inheritance are correct.

## Decision Checklist

When approaching a new ACL inheritance task:

1. [ ] Identify all principals (users and groups) and their required access
2. [ ] Determine the owning user and group for the workspace
3. [ ] Choose the base mode with setgid (e.g., 2770)
4. [ ] For each principal, determine directory perms and file perms
   - Remember: one ACL entry covers both; creation mode differentiates
   - Remember: directory `x` is required for traversal (not just listing)
5. [ ] Set access ACLs on the workspace directory
6. [ ] Set matching default ACLs for inheritance
7. [ ] Ensure the mask (both access and default) allows maximum needed perms
8. [ ] Set `other::---` (or appropriate) in both access and default ACLs
9. [ ] If existing tree: use `setfacl -R -m` + `find -type d -exec setfacl -d -m`
10. [ ] Verify with `getfacl` and test file/directory creation
11. [ ] Test access for each principal (read, write, traverse, create, execute)
12. [ ] Test ancestor directory traversal (every dir in path needs at least `--x`)
