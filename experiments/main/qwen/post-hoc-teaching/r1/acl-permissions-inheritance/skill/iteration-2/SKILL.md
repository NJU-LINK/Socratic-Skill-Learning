---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspaces with correct permission
  inheritance, group propagation via setgid, and differentiated access for
  named users, groups, and others. Covers setting access and default ACLs,
  understanding mask interactions with file creation modes, and ensuring
  permissions propagate correctly through arbitrarily deep directory trees.
---

# ACL Permissions Inheritance

## Overview

This skill configures Linux POSIX ACLs (via `setfacl`/`getfacl`) on shared
workspace directories so that:

- Collaborators (named users and/or groups) get specified access levels
- Restricted users get differentiated access (e.g., read/traverse but not write)
- Outsiders get no access at all
- Permissions propagate correctly to newly created files and subdirectories
- Group ownership propagates via setgid

## Core Concepts

### POSIX ACL Entry Types

Every file/directory with ACLs has these entry types:

| Entry | Meaning |
|-------|---------|
| `user::rwx` | Owner permissions |
| `user:name:rwx` | Named user permissions |
| `group::rwx` | Owning group permissions |
| `group:name:rwx` | Named group permissions |
| `mask::rwx` | Maximum effective permissions for named users, named groups, and owning group |
| `other::rwx` | Everyone else |

**Default ACLs** (prefixed `default:`) exist only on directories. They determine
the ACL that newly created files and subdirectories inherit.

### The Mask

The mask entry is critical. It limits the **effective** permissions for:
- All named user entries (`user:name:---`)
- All named group entries (`group:name:---`)
- The owning group entry (`group::---`)

The mask does NOT limit the owner (`user::`) or others (`other::`).

When displayed by `getfacl`, effective permissions appear as comments:
```
user:runner:r-x    #effective:r--
```
This means the ACL entry is `r-x` but the mask limits it to `r--`.

### ACL Evaluation Algorithm

The POSIX ACL evaluation algorithm is a **four-step decision process** (not
"first match"):

1. **Owner?** If the process UID matches the file owner → use `user::`. Done.
2. **Named user?** If the process UID matches any `user:name:` entry → use
   that entry intersected with `mask::`. Done.
3. **Group match?** Collect ALL matching group entries:
   - `group::` if the process is a member of the owning group
   - Every `group:name:` where the process is a member
   - If any match exists → effective permissions = **union of all matching
     entries**, then intersected with `mask::`. Done.
4. **Otherwise** → use `other::`. Done.

The critical detail at step 3: if a user qualifies through **multiple** group
entries (e.g., owning group + one or more named groups), the kernel takes the
**union** (most permissive combination) of all matching group permissions
before applying the mask. This is "most permissive group match," not "first
match."

**Example:** User `carol` is in both `editors` and `reviewers`. The ACL has
`group:editors:r-x` and `group:reviewers:r--`. Carol's effective group
permissions = `(r-x ∪ r--) ∩ mask = r-x ∩ mask`. She gets the union of all
groups she belongs to, not just the first matching entry.

This algorithm explains why:
- Named user entries take precedence over group membership
- The mask affects named users, named groups, and the owning group, but NOT the owner or others
- Users in multiple groups get the most permissive combination of permissions

### File Creation Mode Interaction

When a new file or directory is created, the kernel intersects the default ACL
with the mode requested by the creating process:

- **Regular files** are typically created with mode `0666` (no execute)
- **Directories** are typically created with mode `0777` (with execute)

This means if a default ACL entry grants `r-x`:
- A new **file** gets effective `r--` (execute stripped by creation mode)
- A new **directory** gets effective `r-x` (execute preserved)

When a collaborator later runs `chmod +x` on a file, the mask is updated to
include execute, restoring the named entry's execute permission. This is how
"read-only unless made executable" patterns work naturally.

### chmod Behavior with ACLs

When a file has ACLs (indicated by `+` in `ls -l`), `chmod` maps **all three**
permission classes to ACL entries:

| chmod class | ACL entry modified |
|---|---|
| Owner bits (u) | `user::` |
| Group bits (g) | `mask::` |
| Other bits (o) | `other::` |

So `chmod +x` adds execute to `user::`, `mask::`, AND `other::` simultaneously.
Named user/group entries (`user:name:`, `group:name:`) are the only entries
chmod does NOT touch.

**Practical consequence:** When a collaborator runs `chmod +x` on a file,
the mask expands to include execute, which restores execute for named user
entries that had it in their ACL but were masked during creation. However,
`other::` also gains execute — visible as `other::--x` in getfacl output.

**Why this is usually safe (directory pruning):** The parent directory has
`other::---`, which blocks outsiders from traversing the path to reach any
file inside. Even if a descendant file ends up with `other::--x`, no outsider
can reach it because they cannot enter the parent directory. This protection
is structural (depends on parent directory ACLs), not inherent to the file's
own ACL. If a variant task uses a less restrictive parent directory, the
`other::` side effect of chmod may need explicit mitigation (e.g., resetting
`other::` via `setfacl -m o::--- file` after chmod).

### setgid for Group Propagation

The setgid bit on a directory (`chmod g+s` or mode `2xxx`) ensures that all
newly created files and subdirectories inherit the parent directory's group
ownership, regardless of the creator's primary group. This is essential for
shared workspaces where collaborators have different primary groups.

### Sticky Bit for Deletion Protection

The sticky bit (`chmod +t`, mode prefix `1`) on a directory restricts file
deletion: only the **file owner**, the **directory owner**, or **root** can
delete or rename files in that directory, even if other users have write
permission on the directory itself.

This is essential when:
- Multiple collaborators have write access to the same directory
- You want to prevent one collaborator from accidentally or maliciously
  deleting another's files
- The workspace has a permissive write policy

**Combining setgid and sticky bit:** The mode prefix digits are additive:
- `2770` = setgid only
- `1770` = sticky only
- `3770` = setgid + sticky (2 + 1 = 3)

Example: `chmod 3770 /path` sets both bits. The setgid propagates group
ownership; the sticky bit protects files from non-owner deletion. In `ls -l`,
the sticky bit appears as `T` (uppercase, no other-execute) or `t` (lowercase,
with other-execute) in the final character of the mode string.

## General Methodology

### Step 1: Analyze Requirements

Identify from the task:
1. **Workspace path** — the shared directory to configure
2. **Owning group** — which group should own the workspace
3. **Collaborators** — who needs full/shared access (users and/or groups)
4. **Restricted principals** — who needs limited access (read-only, traverse-only, etc.)
5. **Outsiders** — everyone else (typically no access)
6. **Permission model** — what rwx combinations each class needs

### Step 2: Create Directory and Set Base Properties

```bash
# Create the workspace directory
mkdir -p /path/to/workspace

# Set ownership (user:group as required)
chown <owner>:<group> /path/to/workspace

# Set base mode with setgid
# The setgid bit (2) ensures group inheritance for new items
# Base permissions set owner and group access; others get nothing
chmod 2770 /path/to/workspace
```

The base mode `2770` means:
- `2` = setgid
- `7` = owner rwx
- `7` = group rwx
- `0` = others nothing

Adjust the base mode digits according to the required permission model.

**⚠️ Critical ordering rule:** Always run `chmod` BEFORE `setfacl`. Never run
`chmod` on a directory after ACLs have been configured, because `chmod`
rewrites the `mask::` entry (and `other::`) based on the group/other bits,
which silently destroys your ACL policy. The named user/group entries appear
unchanged in `getfacl` output, but their effective permissions become limited
by the new mask. If you must run `chmod` after ACLs exist, immediately
reapply the mask with `setfacl -m m::rwx /path` to restore the intended
policy. See Pitfall #1 for a detailed explanation.

### Step 3: Set Access ACLs on the Directory

Set ACL entries for the directory itself. Use `setfacl -m` to modify:

```bash
# Owner permissions (usually rwx)
setfacl -m u::rwx /path/to/workspace

# Named user entries for collaborators (if not covered by group)
setfacl -m u:alice:rwx /path/to/workspace
setfacl -m u:bob:rwx /path/to/workspace

# Named group entries (if using group-based access)
setfacl -m g:projectteam:rwx /path/to/workspace

# Owning group permissions
setfacl -m g::rwx /path/to/workspace

# Restricted user entries
setfacl -m u:runner:r-x /path/to/workspace

# Mask — must be at least as permissive as the most permissive named entry
setfacl -m m::rwx /path/to/workspace

# Others — typically no access
setfacl -m o::--- /path/to/workspace
```

**Key decisions:**
- If collaborators are members of the owning group, they get access through
  `group::` and may not need named user entries. But named user entries give
  explicit control independent of group membership.
- The mask must accommodate the most permissive named entry. If alice needs
  `rwx`, the mask must be at least `rwx`.

### Step 4: Set Default ACLs for Inheritance

Default ACLs determine what new items inherit. They mirror the access ACL
structure but with `default:` prefix:

```bash
# Default owner permissions
setfacl -d -m u::rwx /path/to/workspace

# Default named user entries (same as access entries for collaborators)
setfacl -d -m u:alice:rwx /path/to/workspace
setfacl -d -m u:bob:rwx /path/to/workspace

# Default owning group
setfacl -d -m g::rwx /path/to/workspace

# Default restricted user entries
setfacl -d -m u:runner:r-x /path/to/workspace

# Default mask
setfacl -d -m m::rwx /path/to/workspace

# Default others
setfacl -d -m o::--- /path/to/workspace
```

**Critical principle:** Default ACLs should match the intended long-term
access policy. Every new file and subdirectory will inherit these as its
initial ACL.

### Step 5: Verify

```bash
# Check the full ACL including defaults
getfacl /path/to/workspace

# Test with actual users
su -s /bin/sh alice -c 'touch /path/to/workspace/testfile'
getfacl /path/to/workspace/testfile

# Verify inheritance in subdirectories
su -s /bin/sh alice -c 'mkdir /path/to/workspace/testdir'
getfacl /path/to/workspace/testdir

# Verify restricted access
su -s /bin/sh runner -c 'cat /path/to/workspace/testfile'     # should work
su -s /bin/sh runner -c 'touch /path/to/workspace/badfile' 2>&1  # should fail

# Clean up test artifacts
rm -rf /path/to/workspace/testfile /path/to/workspace/testdir
```

## Recursive ACL Operations

When working with **existing directory trees** (not just new workspaces), you
need to apply ACLs recursively:

```bash
# Apply ACLs recursively to all existing files and directories
setfacl -R -m u:alice:rwx /path/to/workspace
setfacl -R -m u:runner:r-x /path/to/workspace

# Set default ACLs recursively (only affects directories)
setfacl -R -m d:u:alice:rwx /path/to/workspace
setfacl -R -m d:u:runner:r-x /path/to/workspace
```

**Important distinctions:**
- `-R` applies the operation to all files and subdirectories
- `-m d:` (or `default:`) sets default ACLs, which only work on directories
- When using `-R` with default ACLs, setfacl silently skips files (defaults
  only apply to directories)

**Order matters:** Apply access ACLs first, then default ACLs. If you set
both in one command, the access ACLs are applied to all items, and default
ACLs are applied only to directories.

**Mask recalculation:** When applying ACLs recursively, the mask is
recalculated for each file/directory based on the most permissive named
entry on that specific item. This means different files may end up with
different mask values if they have different named entries.

## Complex Policy Topologies

Some variants require **different permissions for different subdirectories**
or **overlapping access patterns**. Here are strategies for complex scenarios:

### Subdirectory-Specific Permissions

When different parts of a workspace need different access levels:

```bash
# Main workspace: full access for team, read-only for auditors
setfacl -m u:team:rwx,g::rwx,u:auditor:r-x /workspace
setfacl -d -m u:team:rwx,g::rwx,u:auditor:r-x /workspace

# Sensitive subdirectory: restrict to senior team only
mkdir /workspace/sensitive
setfacl -m u:senior:rwx,u:team:---,u:auditor:--- /workspace/sensitive
setfacl -d -m u:senior:rwx,u:team:---,u:auditor:--- /workspace/sensitive
```

**Key principle:** Child directories can have **more restrictive** ACLs than
their parents, but inheritance from parent default ACLs still applies. You
must explicitly override inherited entries on the child directory.

### Overlapping Group Memberships

When users belong to multiple groups with different ACL entries, remember
the **union semantics** from the evaluation algorithm:

```bash
# User carol is in both developers and testers groups
# developers get rwx, testers get r-x
setfacl -m g:developers:rwx,g:testers:r-x /workspace

# Carol's effective permissions = (rwx ∪ r-x) ∩ mask = rwx ∩ mask
# She gets the most permissive combination
```

**Design tip:** If you need to **restrict** a user who has broad group
access, use a **named user entry** instead of relying on group entries.
Named user entries take precedence over all group entries in the evaluation
algorithm.

### Conditional Execute Access

When some users need execute on scripts but not on regular files:

```bash
# Default: runner gets r-x (files get r-- due to creation mode)
setfacl -d -m u:runner:r-x /workspace

# When collaborator makes a script executable:
# chmod +x updates the mask to include execute
# runner's r-x entry becomes effective r-x (can now execute)

# For regular files, mask stays rw- (no execute bit from creation mode)
# runner's r-x becomes effective r-- (cannot execute)
```

This pattern works automatically due to the file creation mode interaction.
No special configuration needed beyond setting `r-x` in the default ACL.

## Diagnostic Commands

When troubleshooting ACL issues, use these commands:

```bash
# Full ACL dump with effective permissions
getfacl /path/to/file

# Recursive ACL dump for entire tree
getfacl -R /path/to/directory

# Check specific user's effective permissions
getfacl --test -u:username /path/to/file

# Check specific group's effective permissions
getfacl --test -g:groupname /path/to/file

# Show only access ACLs (no defaults)
getfacl -a /path/to/directory

# Show only default ACLs
getfacl -d /path/to/directory

# Verify setgid bit
ls -ld /path/to/directory  # look for 's' in group execute position
stat -c '%A %a' /path/to/directory

# Check group membership
id username
groups username
```

**Common diagnostic patterns:**
- If a user can't access a file they should, check: (1) named user entry
  exists, (2) mask is permissive enough, (3) parent directory ACLs allow
  traversal, (4) **whether `chmod` was run after `setfacl`**, which may have
  reset the mask to a more restrictive value. Look for `#effective:---` in
  `getfacl` output even though the named entry shows permissions.
- If a user has **too much** access, check: (1) group memberships, (2) union
  of matching group entries, (3) whether `other::` is too permissive, (4)
  whether `chmod` was run after `setfacl` and opened up `other::` or the mask.
- If inheritance isn't working, verify default ACLs exist on the parent
  directory with `getfacl -d /parent`

## Permission Pattern Recipes

### Full Collaborator Access
For users who need complete control:
```bash
setfacl -m u:collaborator:rwx /path
setfacl -d -m u:collaborator:rwx /path
```

### Read-Only Access
For users who should only read files and list directories:
```bash
setfacl -m u:reader:r-x /path      # r-x on directory for traversal
setfacl -d -m u:reader:r-x /path   # r-x default; files get r-- due to creation mode
```

The file creation mode interaction means:
- Directories inherit `r-x` → can list and traverse
- Files inherit `r-x` but creation mode strips execute → effective `r--`
- This is exactly the right behavior for read-only users

### Traverse + Execute (No Write)
For users who need to traverse directories and run scripts but not modify:
```bash
setfacl -m u:runner:r-x /path
setfacl -d -m u:runner:r-x /path
```

Same as read-only at the default level, but when collaborators `chmod +x`
scripts, the mask updates and runner gains execute on those specific files.

### Group-Based Access
When collaborators share a group:
```bash
# Rely on owning group entry instead of named user entries
setfacl -m g::rwx /path
setfacl -d -m g::rwx /path
# Ensure setgid for group propagation
chmod g+s /path
```

### Deny Specific Principal
To explicitly deny a user even if they might qualify through group membership:
```bash
# Note: POSIX ACLs don't have explicit "deny" entries.
# Instead, don't grant them any named entry, and ensure:
# 1. They're not in the owning group
# 2. other:: is set to ---
# 3. They're not in any named group entry that grants access
```

See the **ACL Evaluation Algorithm** in Core Concepts for details on how
POSIX ACLs determine which entry applies to a given user.

## Common Pitfalls

1. **Running chmod after setfacl silently destroys ACL policy**: This is the
   most dangerous operational hazard. When you run `chmod` on a directory that
   already has ACLs, it rewrites the `mask::` entry (and `other::`) based on
   the group/other bits, which can silently invalidate your entire access
   policy. **Example:** After configuring `setfacl -m u:runner:r-x` with
   `mask::rwx`, running `chmod 2700 /path` changes the mask to `---`, locking
   out runner (and all other named users and group members) even though their
   ACL entries still show `r-x`. The named entries appear unchanged in
   `getfacl` output, but their effective permissions become `---` due to the
   mask. Only `user::` (the owner) is unaffected because it's not subject to
   the mask. **The fix:** Always run `chmod` BEFORE `setfacl`, never after.
   If you must run `chmod` on a directory with existing ACLs, immediately
   reapply the mask with `setfacl -m m::rwx /path` to restore the intended
   policy. Default ACLs are NOT affected by chmod, so newly created items
   still inherit correctly — but the directory itself becomes inaccessible.

2. **Forgetting the mask**: If the mask is too restrictive, named entries won't
   have their intended effect. Always set the mask to accommodate the most
   permissive named entry.

3. **Forgetting setgid**: Without setgid, new items get the creator's primary
   group, breaking group-based access for collaborators with different primary
   groups.

4. **Forgetting default ACLs**: Access ACLs only affect the directory itself.
   Without default ACLs, new items get no ACL inheritance and fall back to
   standard Unix permissions modified by umask.

5. **Forgetting chmod modifies three entries**: When ACLs are present,
   `chmod` modifies `user::`, `mask::`, and `other::` — not just the mask.
   This means `chmod +x` adds execute to `other::` as well, which can be a
   concern if parent directories don't prune `other::` access. See the
   "chmod Behavior with ACLs" section for the full mapping and directory
   pruning explanation.

6. **Not testing with actual users**: Permission calculations involve the
   intersection of ACL entries, mask, file creation mode, and group membership.
   Always verify with `su` as each relevant user.

7. **Confusing group:: with named groups**: `group::` is the owning group.
   `group:name:` is a named group entry. They are distinct ACL entries with
   independent permissions.

8. **Assuming "first match" for groups**: When a user matches multiple group
   entries, the kernel takes the **union** of all matching group permissions
   (then intersects with the mask). The order of ACL entries does not matter
   for group evaluation. See the ACL evaluation algorithm above.

## Verification Checklist

- [ ] Directory exists with correct owner:group
- [ ] setgid bit is set (`ls -l` shows `s` in group execute position)
- [ ] Access ACL entries match the required policy
- [ ] Default ACL entries match the required policy
- [ ] Mask is permissive enough for all named entries
- [ ] `other::` denies access to outsiders
- [ ] New files inherit correct ACLs (test with each user class)
- [ ] New subdirectories inherit correct ACLs AND default ACLs
- [ ] Deep nesting works (create 3+ levels deep)
- [ ] Restricted users can traverse but not write
- [ ] Restricted users can read files
- [ ] Restricted users can execute scripts made executable by collaborators
- [ ] Outsiders cannot access anything
- [ ] If using existing directory tree: recursive ACL application worked
- [ ] If using subdirectory-specific permissions: child ACLs override parent defaults correctly
- [ ] If users have overlapping group memberships: union semantics produce expected permissions
