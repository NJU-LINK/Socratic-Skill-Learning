---
name: acl-permissions-inheritance
description: >
  Configure Linux POSIX ACLs on shared directories with correct permission
  topology, inheritance via default ACLs, setgid group propagation, and
  differentiated access for named users/groups versus others. Handles arbitrary
  combinations of collaborators with varying permission levels, mask-aware
  effective permission design, and multi-generation directory trees.
---

# ACL Permissions Inheritance

## Overview

This skill configures POSIX Access Control Lists (ACLs) on Linux shared
workspaces. The core challenge is designing an ACL policy that:

1. Grants differentiated access to multiple principals (users and groups)
2. Propagates correctly to newly created files and subdirectories
3. Uses the ACL mask mechanism to control effective permissions
4. Combines setgid group ownership with named ACL entries for inheritance

## Critical Decision: ACL Entry Precedence

**Before designing your ACL policy, understand how the kernel matches entries.**
This is the single most important concept for correct ACL configuration and
the source of the most common mistakes.

When a process accesses a file, the kernel evaluates ACL entries in strict
order. **The first matching entry wins — entries do NOT accumulate.**

### Matching Algorithm

1. **Owner match**: If the process UID equals the file owner → use `user::`
   permissions. **Stop.** (NOT affected by mask.)
2. **Named user match**: If the process UID matches a `user:name:` entry →
   use that entry AND mask. **Stop.**
3. **Group match**: If any of the process's GIDs match the owning group or
   a named group entry → use the **most permissive** matching group entry
   AND mask. **Stop.**
4. **Other**: Use `other::` permissions. **Stop.** (NOT affected by mask.)

### The Trap: Named User Entries Override Group Membership

If a principal is both a group member AND has a named user entry, the named
user entry wins — even if it's more restrictive.

**Example trap scenario**:

```bash
# alice is a member of editors group
# Setup: group::rwx for editors, but user:alice:r-x (more restrictive)
setfacl -m u::rwx,g::rwx,u:alice:r-x,m::rwx,o::--- /shared

# alice tries to create a file → DENIED
# Why? Step 2 matches: user:alice:r-x → effective r-x → no write permission
# The group::rwx entry is never consulted because step 2 already stopped.

# bob (also in editors, but no named user entry) → ALLOWED
# Why? Step 2 doesn't match. Step 3 matches: group::rwx → effective rwx.
```

### Design Checklist

When setting up ACLs, verify for each principal:

- [ ] If the principal should get access from **group membership**, do NOT
      create a named user entry for them (or ensure the named user entry
      grants at least the permissions you want).
- [ ] If the principal needs **different permissions than their group**,
      create a named user entry with the exact permissions they need.
- [ ] Named user entries and group entries are **never combined**. You cannot
      "add" permissions from both sources.
- [ ] For principals who are both group members and have named entries, the
      named entry is the **sole source** of their ACL-based permissions.

**Rule**: When a principal's access comes partly from group membership and
partly from explicit entries, the named user entry must be set to at least
the broadest permission you want them to have.

## Core Concepts

### POSIX ACL Structure

Every file/directory with ACLs has these entry types:

| Entry | Meaning |
|-------|---------|
| `user::rwx` | Owner (owning user) permissions |
| `user:name:rwx` | Named user permissions |
| `group::rwx` | Owning group permissions |
| `group:name:rwx` | Named group permissions |
| `mask::rwx` | Maximum effective permissions for named entries + owning group |
| `other::rwx` | Everyone else |

**Critical rule**: Effective permission = entry AND mask. The mask acts as an
upper bound for all named user entries, named group entries, and the owning
group entry. It does NOT affect the owner (`user::`) or `other::`.

### Default ACLs (Inheritance)

Directories can have **default ACLs** that serve as templates for new children:

- When a **file** is created, its access ACL is copied from the parent's default
  ACL, then intersected with the creation mode (typically `0666` for files).
- When a **directory** is created, its access ACL is copied from the parent's
  default ACL, intersected with the creation mode (typically `0777`), AND the
  default ACL itself is also copied to the new directory.

The intersection with creation mode primarily affects the **mask**:
- Files created with mode `0666` → mask loses execute bit → `mask::rw-`
- Directories created with mode `0777` → mask keeps all bits → `mask::rwx`

This means named entries retain their full permission bits, but effective
permissions for files lose execute unless the mask is later changed (e.g., via
`chmod +x`).

### setgid and Group Propagation

Setting the setgid bit (`chmod g+s` or mode `2xxx`) on a directory causes:
- All new files and subdirectories inherit the directory's **group ownership**
- This works independently of ACLs and complements them

### chmod Interaction with ACLs

When `chmod` is used on a file with ACLs:
- User bits → modify `user::` entry
- Group bits → modify `mask::` entry (NOT `group::`)
- Other bits → modify `other::` entry
- Named user/group entries are **unchanged**

This means `chmod +x` on a file adds execute to the mask, which can restore
execute access to named entries that had it but were masked out at creation.

## General Method

### Step 0: Map Principals to ACL Matching Paths

Before writing any `setfacl` commands, determine how each principal will
be matched by the kernel. This prevents the precedence trap.

For each principal in your policy, fill in this table:

```
Principal    UID    Groups          Matching Path         Desired Perms
──────────────────────────────────────────────────────────────────────
alice        1001   alice, editors  user:alice:rwx (step 2)  rwx
bob          1002   bob, editors    user:bob:rwx (step 2)    rwx
runner       1003   runner          user:runner:r-x (step 2) r-x
random_user  ?      ?               other::--- (step 4)      ---
```

**Key questions to answer**:
- Does this principal need a **named user entry**, or will they get access
  through **group membership** alone?
- If they're in the owning group AND have a named user entry, the named
  entry wins. Set the named entry to the full permissions you want.
- If they should get group permissions, do NOT create a named user entry
  for them (it would override the group entry).

### Step 1: Analyze the Access Policy

Identify all principals and their required access levels:

```
Principal          → Directories    → Files          → Can create/delete?
─────────────────────────────────────────────────────────────────────────
Owner (user::)     → rwx            → rw- or rwx     → yes (via dir w)
Collaborator A     → rwx            → rw-            → yes
Collaborator B     → rwx            → rw-            → yes
Read-only user     → r-x            → r--            → no
Traverser          → --x            → ---            → no
Others             → ---            → ---            → no
```

Key design decisions:
- **Named user entries** (`user:name:perms`) for specific individuals
- **Named group entries** (`group:name:perms`) when access comes via group
  membership
- **Owning group** (`group::perms`) for the primary collaborating group
- **Mask** set to the union of all needed effective permissions
- **Other** set to the minimum (usually `---`)

### Step 2: Create Directory and Set Base Permissions

```bash
mkdir -p /path/to/shared
chown <owner>:<group> /path/to/shared
chmod 2<base_mode> /path/to/shared
```

The setgid bit (`2` prefix) ensures group inheritance. The base mode should
reflect the desired owner/group/other permissions WITHOUT ACLs (ACLs will
override the group class anyway, but the base mode sets the initial framework).

Common base modes:
- `2770`: owner rwx, group rwx, other --- (fully collaborative, closed)
- `2750`: owner rwx, group r-x, other --- (group can traverse/read only)
- `2700`: owner rwx, group ---, other --- (all access via ACLs only)

### Step 3: Set Access ACLs

```bash
# Owner permissions
setfacl -m u::<owner_perms> /path/to/shared

# Owning group permissions
setfacl -m g::<group_perms> /path/to/shared

# Named user entries (one per collaborator)
setfacl -m u:<name>:<perms> /path/to/shared

# Named group entries (if using group-based access)
setfacl -m g:<group>:<perms> /path/to/shared

# Mask: set to the broadest permission any named entry needs
setfacl -m m::<mask_perms> /path/to/shared

# Others
setfacl -m o::<other_perms> /path/to/shared
```

**Or use a single setfacl command** for atomicity:

```bash
setfacl -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,m::rwx,o::--- /path/to/shared
```

### Step 4: Set Default ACLs for Inheritance

Default ACLs mirror the access ACL structure but use the `-d` flag:

```bash
setfacl -d -m u::<owner_perms> /path/to/shared
setfacl -d -m g::<group_perms> /path/to/shared
setfacl -d -m u:<name>:<perms> /path/to/shared
setfacl -d -m m::<mask_perms> /path/to/shared
setfacl -d -m o::<other_perms> /path/to/shared
```

**Critical**: Default ACL entries should typically match the access ACL entries.
The creation-mode intersection handles the file-vs-directory distinction:
- Set `rwx` in defaults for full collaborators → files get `rw-` effective
  (mask `rw-`), directories get `rwx` effective (mask `rwx`)
- Set `r-x` in defaults for traverse-only users → files get `r--` effective,
  directories get `r-x` effective

### Step 5: Verify

Run a comprehensive verification covering all access dimensions:

```bash
# 1. Check the complete ACL
getfacl /path/to/shared

# 2. Test each principal type
# Collaborators: create, read, write, traverse, execute
su -s /bin/bash <collab> -c "touch /path/to/shared/test && echo 'create OK'"
su -s /bin/bash <collab> -c "cat /path/to/shared/test && echo 'read OK'"
su -s /bin/bash <collab> -c "echo 'x' >> /path/to/shared/test && echo 'write OK'"
su -s /bin/bash <collab> -c "ls /path/to/shared/ && echo 'traverse OK'"

# Read-only/traverse users: read and traverse but NOT create/modify/delete
su -s /bin/bash <reader> -c "cat /path/to/shared/test && echo 'read OK'"
su -s /bin/bash <reader> -c "ls /path/to/shared/ && echo 'traverse OK'"
su -s /bin/bash <reader> -c "touch /path/to/shared/x" 2>&1 && echo "FAIL" || echo "create DENIED (correct)"
su -s /bin/bash <reader> -c "echo 'x' >> /path/to/shared/test" 2>&1 && echo "FAIL" || echo "modify DENIED (correct)"

# Unrelated users: no access at all
su -s /bin/bash <outsider> -c "ls /path/to/shared/" 2>&1 && echo "FAIL" || echo "access DENIED (correct)"

# 3. Test script execution (if applicable)
su -s /bin/bash <collab> -c 'printf "#!/bin/bash\necho ok\n" > /path/to/shared/script.sh && chmod +x /path/to/shared/script.sh'
su -s /bin/bash <reader> -c "/path/to/shared/script.sh && echo 'exec OK'"

# 4. Test inheritance on files and directories
touch /path/to/shared/testfile
getfacl /path/to/shared/testfile   # Check mask is rw- for files
mkdir /path/to/shared/testdir
getfacl /path/to/shared/testdir    # Check mask is rwx for dirs, default ACLs present

# 5. Test deep inheritance
su -s /bin/bash <collab> -c "mkdir -p /path/to/shared/testdir/deep/deeper"
getfacl /path/to/shared/testdir/deep/deeper  # Should have same ACLs + defaults

# 6. Test cross-user collaboration
su -s /bin/bash <collab1> -c "echo 'from collab1' > /path/to/shared/shared_file"
su -s /bin/bash <collab2> -c "cat /path/to/shared/shared_file && echo 'cross-user read OK'"
su -s /bin/bash <collab2> -c "echo 'from collab2' >> /path/to/shared/shared_file && echo 'cross-user write OK'"

# 7. Clean up test items
rm -rf /path/to/shared/testfile /path/to/shared/testdir /path/to/shared/shared_file /path/to/shared/script.sh
```

## Design Patterns

### Pattern: Full Collaborators + Read-Only Traverser

The most common pattern: some users get full access, one user can only
read/traverse, others get nothing.

```
Access ACL:
  user::rwx                    # owner
  user:collab1:rwx             # full collaborator
  user:collab2:rwx             # full collaborator
  user:reader:r-x              # read + traverse
  group::rwx                   # owning group (collaborators)
  mask::rwx                    # don't restrict anyone
  other::---                   # deny all others

Default ACL: (same entries as access ACL)
```

**Why this works for script execution**: When a collaborator creates a file
(mode 0666), reader's effective permission is `r--` (mask `rw-`). When the
collaborator does `chmod +x`, the mask gains `x` → reader's effective becomes
`r-x`, enabling script execution.

### Pattern: Group-Based Access with Named Overrides

When the owning group provides baseline access and named entries override:

```
Access ACL:
  user::rwx
  group::r-x                   # baseline: owning group can read/traverse
  user:power_user:rwx          # override: specific user gets full access
  mask::rwx
  other::---
```

**Precedence note**: `power_user` might also be in the owning group, but the
named user entry `user:power_user:rwx` wins at step 2 of the matching
algorithm. The `group::r-x` entry is never consulted for `power_user`.
This is how you give one group member elevated access without changing
the group entry for everyone else.

### Pattern: Multiple Groups with Different Access Levels

```
Access ACL:
  user::rwx
  group::rwx                   # primary group: full access
  group:viewers:r-x            # secondary group: read + traverse
  mask::rwx
  other::---
```

### Pattern: Group-Only Access (No Named User Entries)

When all collaborators are in the owning group and you want to avoid the
precedence trap entirely, use group-only access:

```bash
mkdir -p /srv/shared
chown root:devteam /srv/shared
chmod 2770 /srv/shared

# No named user entries - all access through group membership
setfacl -m u::rwx,g::rwx,m::rwx,o::--- /srv/shared
setfacl -d -m u::rwx,g::rwx,m::rwx,o::--- /srv/shared
```

**When to use this**: When every collaborator is already a member of the
owning group and you don't need differentiated per-user permissions. This
is simpler and avoids the precedence trap because no named user entries
exist to override group access.

**Trade-off**: You cannot give individual users different permissions.
Everyone in the group gets the same access. If you need to add a
read-only user later, you'll need to add a named user entry for them.

### Pattern: Mask Restriction (Limiting Effective Permissions)

When you want named entries to have broad permissions in the ACL but
limit effective permissions via the mask:

```bash
# Set named entries with full rwx
setfacl -m u:alice:rwx,u:bob:rwx /srv/shared

# But restrict the mask to rw- (no execute for anyone except owner)
setfacl -m m::rw- /srv/shared
```

**Result**: alice and bob have `rwx` in their entries, but effective
permissions are `rw-` (masked). The owner (`user::rwx`) is NOT affected
by the mask and keeps full access.

**When to use this**: When you want to temporarily suspend execute access
for all collaborators without changing individual entries, or when you
want a single control point (the mask) to limit all named entries.

**Warning**: The mask also affects the owning group entry. If you set
`group::rwx` and `mask::rw-`, the group's effective permissions become
`rw-`. Use `-n` (`--no-mask`) when adding entries if you want to set
the mask manually afterward.

### Pattern: Denying Specific Principals

To explicitly deny a user or group (beyond just "others"):

```bash
setfacl -m u:blocked_user:--- /path/to/shared
setfacl -d -m u:blocked_user:--- /path/to/shared
```

This works **because of precedence**: the named user entry `u:blocked_user:---`
matches at step 2 and stops evaluation, preventing the kernel from ever
reaching a group entry that might grant access. Without the named entry,
the user might match at step 3 (group) or step 4 (other) and get unintended
access.

**Important**: In POSIX ACLs, there's no "deny" semantics — `---` simply
means no permissions granted via that entry. The named entry works as a
denial only because it intercepts the matching algorithm before a more
permissive group or other entry could apply.

## Mask Management

The mask is the most subtle part of ACL configuration:

1. **Setting the mask**: `setfacl -m m::rwx dir` — set explicitly
2. **Auto-recalculation**: By default, `setfacl` recalculates the mask to be
   the union of all named entries and the owning group. Use `-n` (or
   `--no-mask`) to prevent this if you want manual mask control.
3. **Mask and chmod**: `chmod` group bits modify the mask, not `group::`
4. **Effective permissions**: Always check `getfacl` output for `#effective:`
   annotations

**When to restrict the mask**: If you want to limit ALL named entries to a
certain level (e.g., no execute for anyone), set the mask accordingly. But
usually you want `mask::rwx` to avoid unintended restrictions.

## Inheritance Deep Dive

### How inheritance works across generations

```
/srv/shared (default ACL set)
├── file1.txt        ← gets access ACL from default, masked by creation mode
├── subdir/          ← gets access ACL from default + copies default ACL
│   ├── file2.txt    ← gets access ACL from subdir's default, masked
│   └── subsubdir/   ← gets access ACL + default from subdir's default
│       └── file3.txt ← still inherits correctly
```

Each generation copies the parent's default ACL as both its access ACL and
its own default ACL. This means inheritance works to arbitrary depth
automatically.

### File vs Directory distinction at creation

The creation mode intersection is the key mechanism:

| Default Entry | File (mode 0666) | Directory (mode 0777) |
|---------------|-------------------|-----------------------|
| `u:name:rwx`  | `rwx` eff `rw-`  | `rwx` eff `rwx`      |
| `u:name:r-x`  | `r-x` eff `r--`  | `r-x` eff `r-x`      |
| `u:name:rw-`  | `rw-` eff `rw-`  | `rw-` eff `rw-`      |
| `m::rwx`      | `rwx` eff `rw-`  | `rwx` eff `rwx`      |

This automatic distinction is why you set `rwx` in defaults for collaborators
— files naturally lose execute (which is correct for most files), while
directories keep it (needed for traversal).

### Creator identity and ownership

When different users create files in the shared directory:

- The **owner** (`user::`) of each new file is the user who created it
- The **group** is inherited from the parent directory (via setgid)
- The **ACL entries** (named users, named groups, mask, other) come from the
  parent's default ACL

**Important**: The owner always gets full access via `user::` regardless of
what the default ACL says for `user::`. If the default says `user::rwx`, the
creator gets `rwx`. If it says `user::rw-`, the creator gets `rw-` (no
execute even on directories they create).

**Cross-user collaboration**: Because named user entries are inherited from
default ACLs, collaborator A can read/write files created by collaborator B,
even though B is the file owner. The named entries (`user:A:rwx`, `user:B:rwx`)
are present on every file, and the mask controls effective permissions.

**Creation order doesn't matter**: Whether alice creates a file first and bob
modifies it, or vice versa, the ACL entries are the same because they come
from the default ACL, not from the creator's umask or identity.

## Troubleshooting

### ACLs not taking effect
- Ensure filesystem supports ACLs (most modern Linux filesystems do)
- Check with `mount | grep <filesystem>` for `acl` option (usually default)
- Verify with `getfacl` that entries are actually set

### Named user can't access despite ACL entry
- Check the mask: `getfacl` shows `#effective:` — if mask restricts, the
  effective permission is less than the entry
- **Check precedence**: Run `id <user>` to see their groups. If they have
  a named user entry, it overrides any group-based access. The named entry
  is the sole source of their permissions.
- Verify the ACL evaluation order: owner → named users → groups → other
- Use `getfacl` and trace through the matching algorithm step by step

### Inheritance not working
- Verify default ACLs exist: `getfacl dir` should show `default:` entries
- Default ACLs only apply to NEW items, not existing ones
- Use `setfacl -R -d -m ...` to set defaults recursively on existing subtrees

### setgid not propagating group
- Ensure setgid bit is set: `chmod g+s dir` or include `2` in mode
- setgid only affects group ownership, not permissions
- ACLs and setgid are complementary mechanisms

## Complete Example

Setting up a shared project workspace:

```bash
# Create directory
mkdir -p /srv/project
chown lead:team /srv/project
chmod 2770 /srv/project

# Set all ACLs in one command (access + default)
setfacl -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:intern:r-x,m::rwx,o::--- /srv/project
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:intern:r-x,m::rwx,o::--- /srv/project

# Verify
getfacl /srv/project
```

This gives alice and bob full access, the intern read+traverse access, and
denies everyone else. New files and directories inherit these permissions
automatically.
