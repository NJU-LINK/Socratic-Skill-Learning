---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspaces with correct access control,
  default ACL inheritance for new files and subdirectories, setgid-based group
  propagation, and mask-aware effective permission management. Handles arbitrary
  combinations of named users, named groups, differentiated permission levels,
  and multi-generational directory trees.
---

# ACL Permissions Inheritance

## Overview

This skill configures POSIX Access Control Lists (ACLs) on Linux shared directories so that:
- Named users and groups receive precisely specified access levels
- Permissions propagate correctly to newly created files and subdirectories via default ACLs
- Group ownership propagates via setgid
- The ACL mask is set to allow intended effective permissions
- Unspecified principals are denied access

## Core Concepts

### POSIX ACL Structure

Every file/directory with ACLs has these entries:

| Entry | Meaning |
|-------|---------|
| `user::<perms>` | Owner permissions |
| `user:<name>:<perms>` | Named user permissions |
| `group::<perms>` | Owning group permissions |
| `group:<name>:<perms>` | Named group permissions |
| `mask::<perms>` | Maximum effective permissions for named users, named groups, and owning group |
| `other::<perms>` | Everyone else |

**Critical rule**: The `mask` entry caps effective permissions for all named user entries, named group entries, and the owning group entry. If the mask is `r-x`, then a named user with `rwx` effectively gets only `r-x`.

### Default ACLs (Inheritance)

Directories can have **default ACLs** that determine the access ACLs of newly created children:

- `default:user::<perms>` → owner entry of new children
- `default:user:<name>:<perms>` → named user entry of new children
- `default:group::<perms>` → owning group entry of new children
- `default:group:<name>:<perms>` → named group entry of new children
- `default:mask::<perms>` → mask entry of new children
- `default:other::<perms>` → other entry of new children

Default ACLs are inherited by **both** new files and new subdirectories. Subdirectories also inherit the default ACLs themselves (so inheritance propagates down the tree).

### File Creation Mode Interaction

When a process creates a file, the requested mode (e.g., 0666 for regular files, 0777 for directories) **intersects** with the default ACL:

- The `user::` entry is intersected with the owner bits of the creation mode
- The `mask::` entry is intersected with the group bits of the creation mode
- The `other::` entry is intersected with the other bits of the creation mode

**Practical consequence**: Regular files are typically created with mode 0666 (no execute). Even if the default ACL has `user:alice:rwx`, the file's mask becomes `rw-`, so alice's effective permissions on the new file are `rw-` (not `rwx`). Directories are typically created with mode 0777, so the full default ACL applies.

This means:
- Named users with `r-x` in default ACLs get `r--` effective on new regular files (can read but not execute)
- Named users with `r-x` in default ACLs get `r-x` effective on new directories (can traverse)
- If a collaborator later does `chmod +x` on a file, the mask gains execute, and the named user's effective permissions become `r-x`

### chmod ↔ ACL Mapping

When a file or directory has an extended ACL (any named user or named group entry), the traditional Unix permission bits are **not independent** of the ACL. They are **views into specific ACL entries**:

| Traditional bits | Map to ACL entry |
|-----------------|-----------------|
| user (owner) bits | `user::` |
| group bits (shown by `ls -l`) | `mask::` (NOT `group::`) |
| other bits | `other::` |

This means `chmod` is a **blunt instrument** that always modifies three ACL entries simultaneously:

- `chmod +x file` → adds execute to `user::`, `mask::`, AND `other::`
- `chmod g-w file` → removes write from `mask::` only (group-class bits map to mask)
- `chmod o+r file` → adds read to `other::`

**Critical consequences**:
1. `chmod g+rwx` on an ACL-managed file modifies the **mask**, not `group::`. This changes effective permissions for all named users and named groups.
2. `chmod +x` on a file with `other::---` will set `other::--x`, breaking the "no access for others" policy.
3. `ls -l` shows the mask in the group permission position. For example, `drwxrws---+` — the `rws` is the mask, not `group::`.
4. After `chmod g-w`, named users' effective permissions may drop even though their ACL entries still say `rwx` — because the mask was reduced.
5. **The `+` indicator**: When `ls -l` shows a permission string like `-rw-rw----+`, the trailing `+` signals that the file has extended ACLs. This is your diagnostic cue that the group field (`rw-` in this example) is the **mask**, not `group::`. Without the `+`, the group field is the actual `group::` entry.

**Use `setfacl -m` for targeted ACL changes** instead of `chmod`:
```bash
# Correct: change only the mask, leaving other:: untouched
setfacl -m m::r-x <path>

# Correct: change only a named user's entry
setfacl -m u:alice:rw- <path>

# Correct: change only other::
setfacl -m o::--- <path>
```

### ACL Evaluation Algorithm

When a process accesses a file with extended ACLs, the kernel determines effective permissions by checking ACL entries in a **specific order**:

1. **File owner**: If the process's effective UID matches the file owner → use `user::` entry (NOT masked)
2. **Named user**: If there's a matching `user:<name>:<perms>` entry → use that entry, **masked by `mask::`**
3. **Group match**: If the process matches the owning group OR any named group entry:
   - Collect ALL matching group entries (owning group `group::` plus any matching `group:<name>:<perms>` entries)
   - Take the **union** of their permissions
   - Apply the `mask::` to the result
4. **Other**: If none of the above match → use `other::` entry (NOT masked)

**Critical implications**:
- A named user entry **takes precedence** over group entries. If alice has `user:alice:rwx` and is also in a group with `group:editors:r-x`, alice gets `rwx` (masked), not the union.
- If a user matches multiple named groups, ALL matching group entries are unioned before masking. For example, if user is in both `group:devs:rwx` and `group:ops:r-x`, the effective permissions are `rwx` (union) masked by `mask::`.
- The `user::` and `other::` entries are **never masked** — only named user entries, named group entries, and the owning group entry are subject to the mask.

**Example**: In the v01 task, alice has `user:alice:rwx` and is also a member of the `editors` group (which has `group::rwx`). The kernel uses the named user entry `user:alice:rwx` (masked by `mask::rwx` → effective `rwx`), NOT the group entry. This is why alice gets full access even though the group entry might suggest otherwise.

### Setgid for Group Propagation

Setting the setgid bit (`chmod g+s` or mode prefix `2`) on a directory causes all new files and subdirectories created within it to inherit the directory's group ownership, regardless of the creator's primary group.

## General Methodology

### Step 1: Analyze the Access Policy

Identify from the task requirements:
1. **The shared directory path** and its required **owner** and **owning group**
2. **Named principals** (users and/or groups) and their required permission levels
3. **The "others" policy** — typically deny all access
4. **Inheritance requirements** — which permissions must propagate to descendants
5. **Any special behaviors** — e.g., traversal-only users, read-only users, execute-only capabilities

### Step 2: Map Requirements to ACL Entries

For each named principal, determine the ACL entry needed:

| Requirement | ACL Entry | Rationale |
|-------------|-----------|-----------|
| Full access (read, write, execute, create, delete) | `rwx` | All permission bits |
| Read + traverse (no modify) | `r-x` | Can list directories, enter them, read files, but not write |
| Read only | `r--` | Can read files and list directories, but not enter or modify |
| Execute only (traverse) | `--x` | Can enter directories but not list or read |
| Read + write (no execute/traverse) | `rw-` | Can read/modify files but not traverse directories |

**Key insight for differentiated access**: A user who should traverse directories and execute scripts but not modify anything needs `r-x`. Due to file creation mode intersection, this gives:
- `r-x` effective on directories (can traverse, list, enter)
- `r--` effective on regular files (can read, but not execute unless chmod +x is applied)
- This naturally implements "read files, execute scripts made executable by others, no modification"

### Step 3: Determine the Mask

The mask must be set to allow the **maximum** effective permissions needed by any named entry:

- If any named user needs `rwx`, mask must be at least `rwx`
- If the most permissive named entry is `r-x`, mask must be at least `r-x`
- The mask should generally match the most permissive named entry to avoid unintended restriction

**Important**: The mask also applies to the owning group entry. If the owning group should have `rwx` but the mask is `r-x`, the group effectively gets only `r-x`.

### Step 4: Configure the Directory

```bash
# 1. Create directory with correct ownership
mkdir -p <path>
chown <owner>:<group> <path>

# 2. Set base permissions with setgid
chmod 2<owner_perms><group_perms><other_perms> <path>
# e.g., chmod 2770 for rwxrws--- 

# 3. Set access ACLs
setfacl -m u:<named_user>:<perms> <path>    # For each named user
setfacl -m g:<named_group>:<perms> <path>   # For each named group
setfacl -m m::<mask_perms> <path>           # Set the mask
setfacl -m o::<other_perms> <path>          # Set others (usually ---)

# 4. Set default ACLs for inheritance (mirror the access policy)
setfacl -d -m u::<owner_perms> <path>       # Default owner entry
setfacl -d -m u:<named_user>:<perms> <path> # For each named user
setfacl -d -m g::<group_perms> <path>       # Default owning group entry
setfacl -d -m g:<named_group>:<perms> <path> # For each named group (if needed)
setfacl -d -m m::<mask_perms> <path>        # Default mask
setfacl -d -m o::<other_perms> <path>       # Default others (usually ---)
```

**Note**: Access ACLs and default ACLs are independent. The access ACL controls the directory itself; the default ACL controls what new children inherit. Typically they mirror each other, but they can differ.

### Step 5: Verify the Configuration

Use this systematic verification checklist to ensure all requirements are met:

```bash
# 1. Verify directory metadata
ls -ld <path>
stat -c "mode=%a owner=%U group=%G" <path>
# Check: mode matches requirement, owner/group correct, setgid bit present if required

# 2. Verify complete ACL configuration
getfacl <path>
# Check: all named users/groups present with correct permissions
# Check: mask allows intended effective permissions
# Check: other:: denies access as required
# Check: default ACLs mirror the access policy for inheritance

# 3. Test inheritance with collaborator-created content
su -c "touch <path>/testfile" <collaborator1>
su -c "mkdir <path>/testdir" <collaborator1>
su -c "touch <path>/testdir/nested" <collaborator2>
getfacl <path>/testfile
getfacl <path>/testdir
getfacl <path>/testdir/nested
# Check: all inherited ACLs match the default ACL policy
# Check: files have correct effective permissions (considering mode intersection)
# Check: subdirectories inherit both access ACLs AND default ACLs
# Check: setgid propagated group ownership to all new items

# 4. Test each principal's effective permissions
# For each named user/group with access:
su -c "cat <path>/testfile" <user>           # Read test
su -c "echo x >> <path>/testfile" <user>     # Write test (should fail if no write)
su -c "touch <path>/newfile" <user>          # Create test (requires write on dir)
su -c "ls <path>/testdir" <user>             # Traverse/list test
su -c "<path>/testdir/script.sh" <user>      # Execute test (if applicable)

# For restricted users (e.g., read-only or traverse-only):
su -c "cat <path>/testfile" <restricted>     # Should succeed if read allowed
su -c "echo x >> <path>/testfile" <restricted> # Should fail if no write
su -c "touch <path>/newfile" <restricted>    # Should fail if no write on dir
su -c "ls <path>/testdir" <restricted>       # Should succeed if r-x on dir

# 5. Test outside users are denied
su -c "ls <path>" <outside_user>             # Should fail
su -c "cat <path>/testfile" <outside_user>   # Should fail
su -c "ls <path>/testdir" <outside_user>     # Should fail

# 6. Test chmod interaction (if relevant to task)
su -c "chmod +x <path>/testdir/script.sh" <collaborator>
getfacl <path>/testdir/script.sh
# Check: mask gained execute, other:: may have changed (inherent POSIX ACL behavior)
su -c "<path>/testdir/script.sh" <restricted> # Should now succeed if r-x

# 7. Clean up test content
rm -rf <path>/testfile <path>/testdir
# Important: do not leave test content if task says not to pre-create
```

## Quick Reference Patterns

### Pattern 1: Shared Workspace with Collaborators and Read-Only User

**Scenario**: Multiple collaborators need full access, one user needs read/traverse only, others denied.

```bash
# Create directory with setgid
mkdir -p /path/to/shared
chown root:collaborators /path/to/shared
chmod 2770 /path/to/shared

# Set access ACLs (combined)
setfacl -m u:alice:rwx,u:bob:rwx,u:reader:r-x,m::rwx,o::--- /path/to/shared

# Set default ACLs for inheritance (combined)
setfacl -d -m u::rwx,u:alice:rwx,u:bob:rwx,u:reader:r-x,g::rwx,m::rwx,o::--- /path/to/shared
```

**Result**: 
- alice/bob: full access to directory and all descendants
- reader: can traverse directories and read files, cannot modify
- others: no access
- New files: reader gets `r--` effective (due to mode intersection), collaborators get `rw-` effective
- New directories: reader gets `r-x` effective, collaborators get `rwx` effective

### Pattern 2: Mask-as-Restriction (Temporary Lockdown)

**Scenario**: All users have `rwx` entries but effective permissions capped at `r-x` via mask.

```bash
# Set ACLs with restrictive mask
setfacl -m u:alice:rwx,u:bob:rwx,m::r-x,o::--- /path/to/shared

# Set default ACLs with same restrictive mask
setfacl -d -m u::rwx,u:alice:rwx,u:bob:rwx,g::rwx,m::r-x,o::--- /path/to/shared
```

**Result**:
- getfacl shows `user:alice:rwx #effective:r-x`
- To unlock full access: `setfacl -m m::rwx /path/to/shared`
- Useful for temporary restrictions without changing individual entries

### Pattern 3: Multiple Groups with Different Access Levels

**Scenario**: Dev group has full access, ops group has read-only, others denied.

```bash
# Create directory
mkdir -p /path/to/shared
chown root:dev /path/to/shared
chmod 2770 /path/to/shared

# Set access ACLs for groups
setfacl -m g:dev:rwx,g:ops:r-x,m::rwx,o::--- /path/to/shared

# Set default ACLs for inheritance
setfacl -d -m u::rwx,g:dev:rwx,g:ops:r-x,g::rwx,m::rwx,o::--- /path/to/shared
```

**Result**:
- Members of dev group: full access (masked by `m::rwx`)
- Members of ops group: read/traverse only (masked by `m::rwx`)
- Users in both groups: union of permissions (`rwx`) masked by mask
- Note: If a user has a named user entry, it takes precedence over group entries

### Pattern 4: Read-Only Shared Workspace

**Scenario**: Everyone can read, only owner can write.

```bash
# Create directory
mkdir -p /path/to/shared
chown root:users /path/to/shared
chmod 2750 /path/to/shared

# Set access ACLs
setfacl -m g::r-x,m::r-x,o::--- /path/to/shared

# Set default ACLs
setfacl -d -m u::rwx,g::r-x,m::r-x,o::--- /path/to/shared
```

**Result**:
- Owner (root): full access
- Group members: read/traverse only
- Others: no access
- New files: group gets `r--` effective (mode intersection)
- New directories: group gets `r-x` effective

### Pattern 5: Deep Directory Tree with Consistent Inheritance

**Scenario**: Multi-level directory structure where all descendants must inherit the same ACL policy.

```bash
# Create top-level directory
mkdir -p /path/to/shared
chown root:editors /path/to/shared
chmod 2770 /path/to/shared

# Set ACLs on top-level (these propagate automatically)
setfacl -m u:alice:rwx,u:bob:rwx,u:reader:r-x,m::rwx,o::--- /path/to/shared
setfacl -d -m u::rwx,u:alice:rwx,u:bob:rwx,u:reader:r-x,g::rwx,m::rwx,o::--- /path/to/shared

# Create subdirectories (they inherit automatically)
mkdir -p /path/to/shared/level1/level2/level3

# Verify inheritance at each level
getfacl /path/to/shared/level1
getfacl /path/to/shared/level1/level2
getfacl /path/to/shared/level1/level2/level3
```

**Result**:
- All subdirectories inherit both access ACLs and default ACLs
- Setgid ensures group ownership propagates
- No additional configuration needed for depth
- Test with different creators to verify consistent behavior

## Common Pitfalls

1. **Forgetting the mask**: If you set named user ACLs but don't set the mask, the mask auto-calculates as the union of all named entries and the owning group. This is usually fine, but be explicit.

2. **Confusing `group::` with named groups**: `group::` is the owning group's base entry. `group:editors:rwx` is a named group entry. They are different ACL entries.

3. **Default ACLs not propagating to subdirectories**: Default ACLs DO propagate to new subdirectories (both as access ACLs and as default ACLs of the subdirectory). This is automatic — no extra configuration needed.

4. **Execute bit on files vs directories**: Remember that file creation mode (typically 0666) strips execute from the mask. A default ACL of `r-x` gives `r--` effective on regular files but `r-x` effective on directories.

5. **Setgid not set**: Without setgid, new files/directories get the creator's primary group, not the shared directory's group. Always set setgid on shared workspace directories.

6. **Others access**: Always explicitly set `other::---` in both access and default ACLs to deny access to unspecified users.

7. **Combining setfacl commands**: You can combine multiple modifications in one command:
   ```bash
   setfacl -m u:alice:rwx,u:bob:rwx,u:runner:r-x,m::rwx,o::--- <path>
   ```

8. **Using `chmod` on ACL-managed files**: `chmod` modifies `user::`, `mask::`, and `other::` simultaneously — it does NOT understand named user/group entries. If a collaborator runs `chmod +x` on a file, `other::` gains execute (breaking `other::---`), and `mask::` gains execute (potentially expanding effective permissions for named users). Always prefer `setfacl -m` for targeted changes. Note that this chmod behavior is inherent to POSIX ACLs and cannot be prevented by configuration — if a task requires `other::---` to survive collaborator chmod operations, that is a process/policy concern, not an ACL configuration concern.

9. **ACL evaluation order matters**: Named user entries take precedence over group entries. If a user has both `user:alice:rwx` and is in a group with `group:devs:r-x`, the named user entry is used (masked), not the group entry. If a user matches multiple named groups, ALL matching group entries are unioned before masking. Always verify effective permissions with `getfacl` and test as each principal.

10. **Forgetting to test nested inheritance**: Default ACLs propagate to subdirectories (both as access ACLs and as default ACLs of the subdirectory), but you must verify this works at multiple levels. Test by creating nested directories and verifying ACLs at each level, not just the first level.

## Adaptation Guide for Variant Tasks

When facing a new variant of this task family:

1. **Different access policy topology**: The same methodology applies regardless of how many users/groups are involved. Map each principal to its required ACL entry. For groups, use `g:<groupname>:<perms>`. For denied principals beyond `other`, add explicit deny entries (note: POSIX ACLs don't have explicit deny — use absence of grant + `other::---`).

2. **Different permission models**: Adjust the permission bits per principal. The mask must accommodate the most permissive named entry. If the task requires the mask itself to restrict permissions, use the **mask-as-restriction pattern**:

   **Example**: If a task requires all named users to have `rwx` ACL entries but effective permissions capped at `r-x`:
   ```bash
   setfacl -m u:alice:rwx,u:bob:rwx,m::r-x /path
   ```
   Result: `getfacl` shows `user:alice:rwx #effective:r-x` — the entry is `rwx` but the mask restricts effective to `r-x`. This is different from giving alice `r-x` directly because `setfacl -m m::rwx` later would instantly grant full access to all named users, whereas changing the entry directly would not. This pattern is useful when you want to maintain the *potential* for full access in the ACL entries but temporarily restrict effective permissions via the mask.

3. **Deeper inheritance trees**: The methodology is identical — default ACLs automatically propagate to all descendant subdirectories. No special configuration needed for depth. Test by creating nested directories and verifying ACLs at each level.

4. **Multiple collaboration groups**: Add named group entries for each group. Remember that a user's effective permissions are determined by the ACL evaluation algorithm: named user entry (if present) takes precedence; otherwise, all matching group entries are unioned and masked. Test with users who are members of multiple groups to ensure the union behavior works as expected.

5. **Different creator identities**: The setgid bit ensures group propagation regardless of who creates the content. Default ACLs ensure permission inheritance regardless of creator identity. Test with different users creating content to verify the behavior is consistent.

6. **Users with both named entries and group membership**: If a user has a named user entry AND is a member of a named group, the named user entry takes precedence (masked). This is usually what you want, but be aware that the group entry is ignored for that user. If you need different permissions for the same user in different contexts, you cannot achieve this with POSIX ACLs alone — you would need separate files/directories with different ACL policies.
