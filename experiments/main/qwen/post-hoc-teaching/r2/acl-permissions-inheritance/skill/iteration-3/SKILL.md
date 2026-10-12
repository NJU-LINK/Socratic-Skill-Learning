---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspaces with correct ownership,
  setgid propagation, per-principal access control, and default-ACL inheritance
  for newly created files and subdirectories. Handles arbitrary mixes of named
  users and groups, varied permission models (read-only, read-execute,
  read-write-execute, denied), and multi-generation directory trees.
---

# ACL Permissions Inheritance

## Overview

This skill configures Linux POSIX Access Control Lists (ACLs) on shared
workspace directories so that:

- Named users and groups receive precisely the permissions specified.
- Permissions propagate correctly to newly created files and subdirectories
  via default ACLs and setgid.
- Principals without explicit access are denied.
- The ACL mask is set so that named entries are not inadvertently restricted.

## Core POSIX ACL Concepts

### ACL Entry Types

| Entry | Meaning |
|---|---|
| `user::rwx` | Owning user (file/directory owner) permissions |
| `user:name:rwx` | Named user permissions |
| `group::rwx` | Owning group permissions |
| `group:name:rwx` | Named group permissions |
| `mask::rwx` | Ceiling for named user entries, named group entries, and owning group |
| `other::---` | Everyone not covered by above entries |

### Access ACL vs Default ACL

- **Access ACL**: Controls permissions on the directory/file itself.
- **Default ACL**: Only valid on directories. Determines the ACL inherited by
  newly created children (files and subdirectories).
- Both must be configured on the root shared directory for correct inheritance.
- Default ACLs propagate recursively: subdirectories inherit the default ACL
  and also receive it as their own default ACL, enabling multi-generation
  inheritance.

### ACL Evaluation Order

When a process accesses a file, the kernel checks ACL entries in this order:

1. If the process UID matches the file owner → use `user::` entry.
2. If the process UID matches a named user entry → use that `user:name:` entry
   (masked by `mask::`).
3. If the process GID or supplementary groups match the owning group or any
   named group entry → use the **union** (bitwise OR) of all matching group
   entries (masked by `mask::`).
4. Otherwise → use `other::` entry.

**Critical implication**: A named user ACL entry takes precedence over any
group-based entry. If a user is in the owning group but also has a named user
ACL entry, the named user entry (masked) is used, NOT the group entry.

### File Creation and the Mask

When a file is created, the inherited ACL permissions are intersected with the
mode parameter from the creating system call:

- Regular files are typically created with mode `0666` (no execute).
- Directories are typically created with mode `0777`.

This means:
- `default:user:name:rwx` on a directory → new files get `user:name:rw-`
  (effective, after mask), new directories get `user:name:rwx`.
- `default:user:name:r-x` on a directory → new files get `user:name:r--`
  (effective), new directories get `user:name:r-x`.

This natural behavior is usually desirable: files are not executable by default,
but collaborators can `chmod +x` to make scripts executable.

**Default ACLs override umask entirely.** When a directory has default ACLs, the
creating process's umask is ignored for new children. Effective permissions come
from `default_ACL_entries AND create_mode` only. This is critical when different
users have different umasks (e.g., root typically 022, regular users 002) —
without default ACLs this would cause inconsistent permission outcomes. With
default ACLs, the outcome is deterministic regardless of who creates the file.

### chmod Interaction with ACLs

When a file has ACL entries (beyond the base three), `chmod` modifies the
**mask** entry, not the `group::` entry. This means:

- `chmod 640 file` sets `mask::r--`, restricting all named entries to read-only
  effective permissions.
- `chmod 770 file` sets `mask::rwx`, allowing full named entry permissions.
- `chmod +x file` adds execute to the mask, enabling execution for named entries
  that have the x bit.

This is important when reasoning about effective permissions after collaborators
modify file modes.

**Critical pattern: chmod +x enables script execution for restricted users.**
When a restricted user (e.g., `u:runner:r-x`) accesses a newly created file:
1. File creation mode is 0666 (no execute)
2. Default ACL `u:runner:r-x` intersects with 0666 → effective `r--`
3. Runner can read but NOT execute the file
4. When a collaborator does `chmod +x script.sh`, the mask changes from `rw-` to `rwx`
5. Runner's `r-x` entry now has effective `r-x` (mask allows it)
6. Runner can now execute the script

This mechanism allows a restricted user to execute scripts made executable by
collaborators, while still being unable to create or modify files.

### Setgid on Directories

Setting the setgid bit (`chmod g+s` or mode `2xxx`) on a directory causes:
- New files and subdirectories inherit the directory's group ownership.
- Combined with default ACLs, this ensures both group ownership and ACL
  permissions propagate correctly.

### `--set` vs `-m` (Modify)

- **`-m` (modify)**: Adds or updates specified ACL entries while preserving all
  existing entries. Use when building up a policy incrementally or when you want
  to add entries without disturbing others.
- **`--set`**: Replaces the **entire** ACL with the specified entries. All
  previous named user/group entries are removed. Requires specifying at minimum
  `user::`, `group::`, and `other::`.
- **`-x` (remove)**: Removes specific ACL entries. Useful for cleanup or when
  a principal should no longer have access.
- **`-b` (remove all)**: Removes all extended ACL entries (named users, named
  groups, mask). Leaves only the base three: `user::`, `group::`, `other::`.

```bash
# --set replaces everything in one atomic operation
setfacl --set u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,m::rwx,o::--- /path

# -x removes a specific entry
setfacl -x u:runner /path

# -b removes all extended ACLs (useful before rebuilding)
setfacl -b /path
```

Use `--set` when remediating a misconfigured workspace where stale entries might
linger. Use `-m` when building a policy step-by-step or adding to an existing
configuration. Use `-x` to remove specific principals. Use `-b` to completely
reset before rebuilding.

## General Procedure

### Step 0: Assess Existing State

Before configuring, determine whether the workspace already exists with content:

```bash
# Check if directory exists and has content
ls -la <workspace_path> 2>/dev/null
getfacl <workspace_path> 2>/dev/null
```

**If the workspace is fresh or can be recreated**: Remove and recreate it for a
 clean slate:
```bash
rm -rf <workspace_path>
mkdir -p <workspace_path>
```

**If the workspace has pre-existing content that must be preserved**: Apply ACLs
recursively (see Step 3b below). Also fix ownership and setgid on existing items.

### Step 1: Analyze Requirements

From the task description, extract:

1. **Workspace path**: The directory to configure (e.g., `/srv/shared`).
2. **Owning group**: The group that should own the workspace (e.g., `editors`).
3. **Collaborators**: Users/groups needing full or substantial access.
   - For each, determine: read, write, execute needs.
   - Note whether access comes from group membership, named user ACL, or both.
4. **Restricted users**: Users needing partial access (e.g., read-only,
   traverse-only).
   - For each, determine exact permission set for files vs directories.
5. **Denied principals**: Users who must have no access at all.
6. **Inheritance requirements**: How deep the ACL propagation must go.

### Step 2: Create Directory and Set Base Ownership

```bash
mkdir -p <workspace_path>
chown <owner_user>:<owning_group> <workspace_path>
chmod <base_mode> <workspace_path>
```

The base mode should include:
- Setgid bit (`2` prefix) so new items inherit the group.
- Appropriate owner/group/other bits. Typically `2770` (rwxrws---) when
  others should have no access.

### Step 3: Set Access ACLs on the Workspace Directory

For each principal, set the appropriate access ACL entry:

```bash
# Named users with full access
setfacl -m u:<user>:rwx <workspace_path>

# Named users with restricted access (e.g., read + traverse)
setfacl -m u:<user>:r-x <workspace_path>

# Named groups
setfacl -m g:<group>:rwx <workspace_path>

# Explicitly deny a specific user (if needed beyond other::---)
setfacl -m u:<user>:--- <workspace_path>

# Ensure others have no access
setfacl -m o::--- <workspace_path>

# Set the mask to allow full named entry permissions
setfacl -m m::rwx <workspace_path>
```

**Mask guidance**: The mask should be set to the widest permission needed by any
named entry. If all collaborators need rwx, set `mask::rwx`. If the most
permissive named entry needs only r-x, set `mask::r-x`. Setting the mask too
narrow will silently restrict other named entries.

### Step 3b: Recursive ACL Application (Pre-Existing Content)

If the workspace already contains files and subdirectories that must be
remediated, apply ACLs recursively. The key constraint: **`-R` applies access
ACLs to all entries (files and dirs), but default ACLs can only be set on
directories.**

```bash
# Access ACLs: apply recursively to everything
setfacl -R -m u:<user>:rwx <workspace_path>
setfacl -R -m u:<restricted_user>:r-x <workspace_path>
setfacl -R -m o::--- <workspace_path>
setfacl -R -m m::rwx <workspace_path>

# Default ACLs: directories only (use find)
find <workspace_path> -type d -exec setfacl -d -m u:<user>:rwx {} +
find <workspace_path> -type d -exec setfacl -d -m u:<restricted_user>:r-x {} +
find <workspace_path> -type d -exec setfacl -d -m o::--- {} +
find <workspace_path> -type d -exec setfacl -d -m m::rwx {} +
find <workspace_path> -type d -exec setfacl -d -m u::rwx {} +
find <workspace_path> -type d -exec setfacl -d -m g::rwx {} +

# Also fix ownership and setgid on existing directories
find <workspace_path> -type d -exec chgrp <owning_group> {} +
find <workspace_path> -type d -exec chmod g+s {} +
```

**Note**: When applying access ACLs recursively, files will get the same entries
as directories (e.g., `u:alice:rwx` on a file). This is usually fine — the file
creation mode intersection only affects newly created files. For existing files,
the access ACL is applied as-is. If you need files to have different permissions
than directories (e.g., no execute on files), use a two-pass approach:

```bash
# Directories: rwx
find <workspace_path> -type d -exec setfacl -m u:<user>:rwx {} +
# Files: rw- (no execute)
find <workspace_path> -type f -exec setfacl -m u:<user>:rw- {} +
```

### Step 4: Set Default ACLs for Inheritance

Mirror the access ACL as default ACLs so children inherit the same policy:

```bash
# Default owning user permissions (for new items' owner)
setfacl -d -m u::rwx <workspace_path>

# Default owning group permissions
setfacl -d -m g::rwx <workspace_path>

# Default named user entries (same as access ACL)
setfacl -d -m u:<user>:rwx <workspace_path>
setfacl -d -m u:<user>:r-x <workspace_path>

# Default named group entries
setfacl -d -m g:<group>:rwx <workspace_path>

# Default other (deny)
setfacl -d -m o::--- <workspace_path>

# Default mask (must match or exceed access mask)
setfacl -d -m m::rwx <workspace_path>
```

**Important**: Default ACLs for `user::` and `group::` should typically be `rwx`
to allow full permissions for the owner and owning group of new items. The
actual effective permissions on files will be reduced by the file creation mode
(no execute for regular files).

### Step 5: Verify

```bash
# Check the full ACL configuration
getfacl <workspace_path>

# Test inheritance by creating a test file and subdirectory
# (only if task allows pre-creating test content)
```

Verify:
- Access ACL entries match the required policy.
- Default ACL entries mirror the access policy for inheritance.
- The setgid flag is set (`flags: -s-` in getfacl output).
- The mask is wide enough for all named entries.
- `other::---` denies access to non-collaborators.

## Permission Patterns

### Full Collaborator (read + write + execute)

For users who need to create, edit, delete files and traverse directories:

```
Access:  u:<user>:rwx
Default: u:<user>:rwx
```

Effective on new files: `rw-` (create mode 0666 masks out x)
Effective on new dirs: `rwx`

### Read-Only / Traverse User

For users who should read files, traverse directories, execute scripts, but
NOT create/modify/delete:

```
Access:  u:<user>:r-x
Default: u:<user>:r-x
```

Effective on new files: `r--` (can read, cannot write or execute)
Effective on new dirs: `r-x` (can traverse and list, cannot create/delete)
Can execute scripts that collaborators make executable (the file's ACL will
show `r-x` effective after chmod +x adjusts the mask).

### Explicitly Denied User

For users who must have absolutely no access:

Option A: Rely on `other::---` (no named entry needed).
Option B: Set explicit deny if the user might match a group entry:

```
Access:  u:<user>:---
Default: u:<user>:---
```

This is needed when a denied user is a member of a group that has been granted
access. The named user entry (even with `---`) takes precedence over group
entries in ACL evaluation.

### Group-Based Access

When access is granted to a group rather than individual users:

```
Access:  g:<group>:rwx
Default: g:<group>:rwx
```

All members of the group receive the specified permissions (masked by `mask::`).

### Mask as Deliberate Restriction

The mask can be used intentionally to cap effective permissions for all named
entries. This is useful when you want to set broad ACL entries but restrict
what's actually effective:

```bash
# Set alice to rwx in the ACL entry
setfacl -m u:alice:rwx /path

# But restrict the mask to r-x
setfacl -m m::r-x /path

# Result: alice's effective permissions are r-x (rwx AND r-x)
```

**Use cases:**
- Temporarily restrict access without removing ACL entries
- Set a "maximum effective permission" ceiling for all named users/groups
- Implement policies where the ACL entry specifies intent but the mask enforces policy

**Important:** The mask affects ALL named user entries, ALL named group entries,
and the owning group entry. It does NOT affect the owning user (`user::`) or
`other::` entries.

## Complex Access Policy Topologies

Real-world scenarios often involve multiple groups, overlapping memberships, and
asymmetric access requirements. This section provides a decision framework for
translating complex requirements into ACL configuration.

### Decision Framework: From Requirements to ACL Entries

**Step 1: Identify all principals and their required access levels.**

Create a table:

| Principal | Type | Required Access | Notes |
|---|---|---|---|
| alice | user | rwx | Full collaborator |
| bob | user | rwx | Full collaborator |
| developers | group | rwx | Team with full access |
| reviewers | group | r-x | Can read and traverse |
| auditor | user | r-- | Read-only, in developers group |
| intern | user | --- | Denied, in developers group |

**Step 2: Determine the mask.**

The mask must be at least as permissive as the most permissive named entry.
If developers need rwx and reviewers need r-x, the mask must be `rwx`.

**Step 3: Handle overlapping memberships.**

If a user is in multiple groups, the ACL evaluation uses the **union** (bitwise
OR) of all matching group entries. For example, if `g:teamA:r-x` and
`g:teamB:-wx` are both set and alice is in both groups, alice gets `rwx`
(r-x OR -wx = rwx, before mask). If you need different behavior:

- **Override with named user entry**: Add `u:<user>:<perms>` to override group
  membership. Named user entries take precedence over all group entries.
- **Explicit deny**: If a user must be denied despite group membership, add
  `u:<user>:---`. This overrides any group entry.

**Example**: auditor is in the developers group (rwx) but needs only r--.
Solution: `u:auditor:r--` (named user entry overrides group entry).

**Step 4: Set both access and default ACLs.**

For each principal, set both the access ACL (on the directory) and the default
ACL (for inheritance):

```bash
# Access ACLs
setfacl -m u:alice:rwx /path
setfacl -m u:bob:rwx /path
setfacl -m g:developers:rwx /path
setfacl -m g:reviewers:r-x /path
setfacl -m u:auditor:r-- /path
setfacl -m u:intern:--- /path
setfacl -m m::rwx /path
setfacl -m o::--- /path

# Default ACLs (mirror access ACLs)
setfacl -d -m u::rwx /path
setfacl -d -m g::rwx /path
setfacl -d -m u:alice:rwx /path
setfacl -d -m u:bob:rwx /path
setfacl -d -m g:developers:rwx /path
setfacl -d -m g:reviewers:r-x /path
setfacl -d -m u:auditor:r-- /path
setfacl -d -m u:intern:--- /path
setfacl -d -m m::rwx /path
setfacl -d -m o::--- /path
```

### Multiple Groups with Different Permission Levels

When multiple groups need different access levels, set each group's ACL entry
independently. The mask must accommodate the most permissive group.

**Example**: developers (rwx), reviewers (r-x), auditors (r--)

```bash
setfacl -m g:developers:rwx /path
setfacl -m g:reviewers:r-x /path
setfacl -m g:auditors:r-- /path
setfacl -m m::rwx /path  # Must be rwx to allow developers
```

**Effective permissions**:
- developers members: `rwx` (rwx AND rwx mask)
- reviewers members: `r-x` (r-x AND rwx mask)
- auditors members: `r--` (r-- AND rwx mask)

**User in multiple groups**: If alice is in both developers and reviewers, the
kernel takes the union: `rwx OR r-x = rwx`. In this case the result happens to
match the most permissive entry, but in general with complementary group
permissions (e.g., `g:teamA:r-x` + `g:teamB:-wx`), the union gives `rwx` —
permissions accumulate across all matching groups.

### Asymmetric Access Patterns

Some collaboration scenarios require asymmetric access: Team A can read Team B's
files, but not vice versa. This requires careful ACL design.

**Pattern**: Use separate named user/group entries for each direction of access.

**Example**: 
- Team A (alice, bob) can read and write Team B's files
- Team B (charlie, dave) can only read Team A's files
- Both teams need to traverse the shared directory

**Solution**:
```bash
# Team A members get rwx
setfacl -m u:alice:rwx,u:bob:rwx /path

# Team B members get r-x (read + traverse only)
setfacl -m u:charlie:r-x,u:dave:r-x /path

# Set mask and other
setfacl -m m::rwx,o::--- /path

# Mirror as default ACLs
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:charlie:r-x,u:dave:r-x,m::rwx,o::--- /path
```

**Note**: This approach uses named user entries rather than groups, which provides
fine-grained control. If you need group-based asymmetric access, you may need
multiple directories or a more complex ACL structure.

### Denial Patterns Beyond `other::---`

When you need to deny specific users or groups while granting access to others:

**Pattern 1: Deny a user who is in a granted group**

```bash
# Grant group access
setfacl -m g:developers:rwx /path

# Deny specific user who is in developers
setfacl -m u:intern:--- /path
```

The named user entry `u:intern:---` takes precedence over the group entry.

**Pattern 2: Deny a specific group**

```bash
# Grant access to most users
setfacl -m g:developers:rwx /path

# Deny a specific group
setfacl -m g:contractors:--- /path
```

**Important**: Group entries are evaluated by checking if the user is a member.
If a user matches multiple group entries, the **union** (bitwise OR) of all
matching entries is used — permissions accumulate across all groups the user
belongs to. To deny or restrict a user who is in multiple groups, you must use
a named user entry `u:<user>:---` (or `u:<user>:<restricted_perms>`), which
takes precedence over all group entries.

## Combining with Setgid for Group Propagation

The setgid bit and default ACLs work together:

1. **Setgid** ensures new files/dirs inherit the parent's group ownership.
2. **Default ACLs** ensure new files/dirs inherit the permission policy.

Both are needed. Without setgid, new files get the creator's primary group.
Without default ACLs, new files get permissions based on the creator's umask.

## Reading Effective Permissions

The `getfacl` output shows both the ACL entry and the effective permissions
(after mask application). Understanding this is critical for verification:

```bash
# Example getfacl output for a file
user::rw-
user:alice:rwx	#effective:rw-
user:bob:rwx	#effective:rw-
user:runner:r-x	#effective:r--
group::rwx	#effective:rw-
mask::rw-
other::---
```

**How to read this:**
- `user:alice:rwx` is the ACL entry (what was configured)
- `#effective:rw-` is what alice actually gets (entry AND mask)
- The mask `rw-` restricts all named entries to at most `rw-`
- Runner's `r-x` entry becomes effective `r--` (no execute because mask lacks x)

**To determine what a user can do:**
1. Find the user's ACL entry (named user, or matching group, or other)
2. Apply the mask (for named users and groups)
3. The result is the effective permission

**Common confusion:** The `group::` entry in getfacl output may differ from what
`ls -l` shows for the group class. When ACLs are present, `ls -l` shows the
mask, not `group::`. Always use `getfacl` for accurate permission analysis.

## Common Pitfalls

1. **Forgetting default ACLs**: Access ACLs alone don't propagate. Always set
   matching default ACLs on directories.

2. **Mask too restrictive**: If `mask::r-x` is set, then `user:alice:rwx` has
   effective permissions of only `r-x`. Always set the mask to the widest
   permission needed.

3. **Confusing `group::` with mask**: When ACLs are present, `chmod` changes
   the mask, not `group::`. The `group::` entry in `getfacl` output may show
   different permissions than what `ls -l` shows for the group class.

4. **Not setting setgid**: Without setgid, new files get the creator's primary
   group, breaking group-based access policies.

5. **Named user entry needed for denial**: If a user is in a group that has
   been granted access, simply omitting them from ACLs won't deny them — they
   still match the group entry. You must add an explicit `u:<user>:---` entry.

6. **Default ACL `user::` should be `rwx`**: Setting `default:user::r--` would
   mean new file owners can only read their own files. The default `user::`
   should typically be `rwx` to let owners have full control of their files.

7. **Forgetting recursive application on existing trees**: If the workspace
   already has content, setting ACLs only on the root directory does NOT fix
   existing children. Use `setfacl -R` for access ACLs and `find -type d` for
   default ACLs.

8. **Using `-m` when `--set` is needed**: If remediating a misconfigured tree,
   stale named entries from a previous configuration will persist with `-m`.
   Use `--set` on the root directory to replace the entire ACL atomically, or
   use `setfacl -b` to remove all ACLs before rebuilding.

9. **Assuming umask affects ACL-inherited permissions**: Default ACLs completely
   override umask. If permissions seem wrong after file creation, check the
   default ACLs, not the user's umask.

10. **File owner uses `user::` not named entry**: When a user who is the file
    owner accesses the file, the `user::` entry is used, NOT any `user:name:`
    entry. The mask does NOT apply to `user::` or `other::`. This means if alice
    creates a file, alice's access is governed by `default:user::rwx` (which
    becomes `user::rw-` on files), not by `user:alice:rwx`.

11. **Mask doesn't apply to `user::` or `other::`**: The mask only restricts
    named user entries, named group entries, and the owning group entry. The
    owning user (`user::`) and `other::` entries are not affected by the mask.

12. **`setfacl -R` applies mask recursively**: When using `-R` to fix existing
    trees, the mask is set on all files and directories. If you need different
    masks for files vs directories (rare), use separate `find` commands.

## Worked Example

**Task**: Configure `/srv/shared` for group `editors` with:
- alice and bob: full access (rwx)
- runner: read + traverse only (r-x)
- others: no access
- Inheritance for all new content

**Solution**:

```bash
# Create directory with setgid and base permissions
mkdir -p /srv/shared
chown root:editors /srv/shared
chmod 2770 /srv/shared

# Access ACLs
setfacl -m u:alice:rwx /srv/shared
setfacl -m u:bob:rwx /srv/shared
setfacl -m u:runner:r-x /srv/shared
setfacl -m o::--- /srv/shared
setfacl -m m::rwx /srv/shared

# Default ACLs for inheritance
setfacl -d -m u::rwx /srv/shared
setfacl -d -m g::rwx /srv/shared
setfacl -d -m u:alice:rwx /srv/shared
setfacl -d -m u:bob:rwx /srv/shared
setfacl -d -m u:runner:r-x /srv/shared
setfacl -d -m o::--- /srv/shared
setfacl -d -m m::rwx /srv/shared
```

**Result verification** (`getfacl /srv/shared`):
```
# file: srv/shared
# owner: root
# group: editors
# flags: -s-
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

**Inheritance behavior**:
- New file by alice: `user::rw-`, `user:alice:rwx #effective:rw-`,
  `user:bob:rwx #effective:rw-`, `user:runner:r-x #effective:r--`,
  `mask::rw-`, `other::---`
- New directory by bob: full ACLs inherited including defaults, setgid set,
  group = editors.
