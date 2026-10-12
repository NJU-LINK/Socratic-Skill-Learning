---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux for shared workspaces with fine-grained
  per-principal access control, setgid-based group propagation, and default
  ACL inheritance for newly created files and subdirectories. Handles
  arbitrary combinations of named users, named groups, permission sets,
  read-only collaborators, and denial policies.
---

# POSIX ACL Configuration for Shared Workspaces with Inheritance

## Overview

This skill configures Linux POSIX Access Control Lists (ACLs) to implement
shared workspace policies where multiple principals (users and groups) need
differentiated access to a directory tree, with permissions that propagate
correctly to newly created descendants.

## Core Concepts

### POSIX ACL Entry Types

Every file or directory with ACLs has these entry classes:

| Entry | Meaning | Masked? |
|---|---|---|
| `user::` | File owner permissions | No |
| `user:name:` | Named user permissions | Yes (by mask) |
| `group::` | Owning group permissions | Yes (by mask) |
| `group:name:` | Named group permissions | Yes (by mask) |
| `mask::` | Max effective perms for named entries + owning group | N/A |
| `other::` | Everyone else | No |

### ACL Permission Evaluation Order

When a process accesses a file, the kernel checks in this order:
1. **Owner match** (process UID == file owner UID) → use `user::` (NOT masked)
2. **Named user match** (process UID matches a `user:name:` entry) → use that entry, **masked**
3. **Group match** (process is member of owning group OR any named group with an ACL entry):
   - Collect ALL matching group entries (owning group `group::` + all `group:name:` entries where user is a member)
   - Take the **union** of all matching group permissions
   - Apply the mask to the union
4. **Fall through** → use `other::` (NOT masked)

The first matching class wins. If a user matches a named user entry, group
entries are never consulted for that user.

**Multiple group membership**: If a user is a member of multiple groups that have ACL entries (e.g., `group:devteam:rwx` and `group:testteam:r-x`), the kernel takes the union of all matching group permissions, then masks the result. The user gets the most permissive access from any matching group.

### The Mask

The mask entry limits effective permissions for ALL of:
- Named user entries (`user:name:`)
- Named group entries (`group:name:`)
- Owning group entry (`group::`)

It does NOT affect `user::` (owner) or `other::`.

Effective permissions = entry permissions AND mask.

### Default ACLs (Inheritance)

Only directories can have default ACLs. When a new child (file or subdirectory)
is created inside a directory with default ACLs:

1. The child's **access ACL** is derived from the parent's default ACL,
   intersected with the creation mode:
   - Regular files are typically created with mode `0666` (no execute)
   - Directories are typically created with mode `0777`
   - The intersection applies to the mask and all entry classes

2. If the child is a **directory**, it also inherits the parent's default ACLs
   as its own default ACLs (enabling multi-level propagation).

**Critical implication**: A default ACL of `user:runner:r-x` will result in:
- New directories: `user:runner:r-x` effective (mask = r-x from mode 0777)
- New regular files: `user:runner:r--` effective (mask = rw- from mode 0666)
- Scripts later chmod'd to executable: mask updates, runner can execute

**Important**: When a directory has default ACLs, the process umask is **IGNORED**. The file's permissions are determined solely by the default ACL intersected with the creation mode requested by the application (typically 0666 for files, 0777 for directories). This means different users with different umask settings will create files with identical ACL-inherited permissions.

### chmod ↔ ACL Mask: Bidirectional Coupling (CRITICAL)

When a file or directory has extended ACLs, the traditional "group" permission
bits displayed by `ls -l` and `stat` **reflect the ACL mask, not `group::`**.
This creates a dangerous bidirectional coupling:

- **`chmod` modifies the ACL mask**, not the owning group entry.
- **`setfacl` may recalculate the mask** from the union of named entries + `group::`.

**Consequence — ordering matters:**
- **chmod BEFORE setfacl** (safe): `setfacl` recalculates the mask from named
  entries, overriding whatever chmod set.
- **chmod AFTER setfacl** (DANGEROUS): `chmod g-w` or `chmod 750` silently
  narrows the mask, crippling ALL named user/group entries. Example: if you
  set `u:alice:rwx` then run `chmod 750`, the mask becomes `r-x`, and alice's
  effective permissions silently drop to `r-x` with no warning.

**Rule**: Never run `chmod` on an ACL'd path to change group-class permissions
— modify ACL entries directly with `setfacl`. If `chmod` must be used (e.g.,
to set setgid or sticky bit), run it BEFORE `setfacl`, or re-apply `setfacl`
afterward.

To set the mask explicitly without `setfacl` auto-recalculating it:
```bash
setfacl -n -m m::r-x <path>   # -n prevents mask recalculation
```

### setgid on Directories

Setting the setgid bit (`chmod g+s` or mode `2xxx`) on a directory causes
new files and subdirectories to inherit the parent's group ownership rather
than the creator's primary group. This is essential for shared workspaces
where multiple users create content that should remain accessible to the group.

### Sticky Bit for Deletion Protection

When multiple collaborators have write access to the same directory, any
collaborator can delete any other's files (deletion requires write+execute on
the parent directory, not on the file itself). The sticky bit (`chmod +t`,
mode bit `1`) restricts deletion so only the file owner, the directory owner,
or root can delete/rename entries.

Use `chmod 3770` (setgid + sticky + rwxrwx---) when a workspace has several
writers who should not destroy each other's work. The sticky bit is inherited
by subdirectories via default ACLs if included in the base mode before ACLs
are set.

## Decision Framework: Translating Requirements to ACL Entries

### Choosing Entry Types

**Named user entries** (`u:name:perms`) — use when:
- Access must be granted/denied to specific individuals
- Different users need different permission levels
- A user must be explicitly denied despite group membership

**Named group entries** (`g:name:perms`) — use when:
- Access should be granted to all members of a team/role
- Team membership changes frequently (easier to manage group membership than ACLs)
- All group members need the same permissions

**Owning group entry** (`g::perms`) — use when:
- The directory's owning group should have baseline access
- Combined with setgid for group ownership propagation

**Explicit denial** (`u:name:---` or `g:name:---`) — use when:
- A user/group must be denied despite broader access patterns
- The user is a member of a group that has access, but should be excluded
- `other::---` is insufficient (e.g., when other class needs some access but specific users must be blocked)

### Decision Tree for Principal Access

```
For each principal mentioned in requirements:
  ├─ Is it the file/directory owner?
  │   └─ Set u:: (owner entry) — NOT masked
  │
  ├─ Is it the owning group (and setgid is used)?
  │   └─ Set g:: (owning group entry) — masked
  │
  ├─ Is it a named user with specific requirements?
  │   └─ Set u:username:perms — masked
  │
  ├─ Is it a named group whose members need access?
  │   └─ Set g:groupname:perms — masked
  │
  └─ Does the principal need to be explicitly denied?
      └─ Set u:username:--- or g:groupname:--- — masked

For everyone else:
  └─ Set o::perms (typically --- for restricted workspaces)
```

### Determining the Mask

The mask must be the **union** of all permission bits needed by named entries and the owning group:

```
mask = u:alice:perms | u:bob:perms | g:team:perms | g::perms
```

Example: If alice needs `rwx`, bob needs `r-x`, and the group needs `rwx`, the mask must be `rwx`.

**Important**: The mask limits effective permissions. If you set `u:alice:rwx` but the mask is `r-x`, alice only gets effective `r-x`.

### Handling Complex Scenarios

**Scenario: User in group but needs different permissions**
- User is member of `editors` group (which has `g::rwx`)
- But this specific user should only have `r-x`
- Solution: Add explicit `u:username:r-x` — named user entry takes precedence over group entries

**Scenario: Explicit denial despite group membership**
- User is member of `developers` group (which has `g:developers:rwx`)
- But this user must have NO access
- Solution: Add explicit `u:username:---` — named user entry with no permissions overrides group entry

**Scenario: Different permissions at different directory levels**
- Top-level directory: alice has `rwx`, bob has `r-x`
- Subdirectory: bob should have `rwx` (elevated access)
- Solution: Set different ACLs on each directory. Default ACLs on parent only affect NEW children, not existing ones. Use `setfacl -m` on the subdirectory to override.

**Scenario: Mixed group + named user access (resilient team workspace)**
- Group provides baseline access for all team members
- Named user entries pin critical individuals whose access must survive group changes
- Use `group::rwx` (or `g:teamname:rwx`) for the team + `u:name:rwx` for pinned individuals
- Named user entry takes precedence when both match, but the group entry still serves non-pinned members

**Why combine both?** When you set both `group::rwx` and `user:alice:rwx`:
- **Group entry** provides collective baseline: any editors member automatically gets rwx. Adding new team members requires only `usermod -aG editors dave`, no ACL changes.
- **Named user entries** provide guaranteed individual access: even if alice is removed from editors, she retains access through `u:alice:rwx`.
- **Together they create resilience**: group membership controls the team roster; named entries pin critical individuals.

**Evaluation consequence**: When bob (in editors + has `u:bob:rwx`) accesses a file owned by alice:
1. Is bob the owner? No.
2. Does bob match a named user entry? **Yes** → use `u:bob:rwx`, masked. **Evaluation stops here.**
3. The `group::rwx` entry is **never consulted** for bob, even though bob is in editors.

Now imagine dave (added to editors, no named entry) accesses the same file:
1. Owner? No. Named user match? No.
2. Owning group match? **Yes** (dave is in editors) → use `group::rwx`, masked.

Both bob and dave get the same effective permissions, but through different ACL entries with different resilience properties. Bob's access survives group removal; dave's access is revoked on group removal.

**When to use each strategy:**
- **Group only** (`group::rwx`): All members need identical access, simple roster management via group membership. Best for teams where members come and go frequently.
- **Named users only** (`u:name:rwx`): Per-user tailoring, no group structure. Best when each user needs different permissions or there's no natural team grouping.
- **Mixed** (group + named users): Team baseline + individual guarantees. Best for collaborative workspaces where most team members need standard access, but key individuals must retain access regardless of group membership changes. This is the v01 pattern.

## General Procedure

### Step 1: Analyze Requirements

Identify from the task:
- **Target path(s)**: The shared directory/directories to configure
- **Owner and group**: Who owns the directory and what group controls access
- **Base mode**: The traditional Unix permission bits (often `2770` for
  collaborative workspaces with setgid, or `3770` if sticky bit needed)
- **Principals and their permissions**: Each user/group and what they need:
  - Full collaborators: typically `rwx`
  - Read-only/traversal users: `r-x` on directories, `r--` effective on files
  - Denied users: explicit `u:name:---` entry or rely on `other::---`
- **Inheritance needs**: Whether default ACLs are required and what they
  should contain
- **Existing content**: Whether the directory already has files/subdirectories that need ACL updates

### Step 2: Create or Prepare Directory

**For new directories:**
```bash
mkdir -p <path>
chown <owner>:<group> <path>
chmod <mode> <path>    # e.g., 2770 for setgid + rwxrwx---
```

**For existing directories:**
```bash
# Verify current state
ls -ld <path>
getfacl <path>

# Adjust ownership/mode if needed (BEFORE setting ACLs)
chown <owner>:<group> <path>
chmod <mode> <path>
```

The mode `2770` means: setgid (2) + owner rwx (7) + group rwx (7) + others --- (0).

### Step 3: Clear Existing ACLs (if starting fresh)

```bash
setfacl -b <path>
```

This removes all extended ACL entries, starting clean. Skip this if you want to modify existing ACLs.

### Step 4: Set Access ACLs on the Directory

Use `setfacl -m` to set multiple entries at once:

```bash
# Template — replace with actual principals and permissions from requirements:
setfacl -m u::<owner_perms>,g::<group_perms>,u:<user1>:<perms>,u:<user2>:<perms>,g:<group>:<perms>,o::<other_perms> <path>
```

**Example for v01-style requirements:**
```bash
setfacl -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,o::--- /srv/shared
```

**Key decisions:**
- `u::rwx` — owner gets full access
- `g::rwx` — owning group gets full access (adjust per requirements)
- `u:name:rwx` — named collaborators get full access
- `u:name:r-x` — read-only users get traverse + read (no write)
- `u:name:---` — explicit denial for specific users
- `g:name:rwx` — named group members get full access
- `o::---` — others get nothing (adjust per requirements)

### Step 5: Set Default ACLs for Inheritance

Default ACLs determine what access ACLs newly created children will receive:

```bash
# Template — mirror access ACLs for named entries:
setfacl -d -m u::<owner_perms>,g::<group_perms>,u:<user1>:<perms>,u:<user2>:<perms>,g:<group>:<perms>,o::<other_perms>,m::<mask> <path>
```

**Example for v01-style requirements:**
```bash
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,o::---,m::rwx /srv/shared
```

**Mask in default ACLs**: Set `m::rwx` (or whatever the maximum needed
permission is) so that named entries are not unnecessarily restricted. The
actual effective permissions on created files will still be limited by the
intersection of this default mask with the file creation mode.

**Important**: Default ACLs should mirror the access ACLs for named entries,
so that the permission policy is consistent across the directory tree.

### Step 6: Handle Existing Content (if applicable)

If the directory already has files/subdirectories that need the new ACL policy:

```bash
# Apply access ACLs recursively to all existing files/dirs
setfacl -R -m u:alice:rwx,u:bob:rwx <path>

# Apply default ACLs recursively to all existing subdirectories
setfacl -R -d -m u:alice:rwx,u:bob:rwx,m::rwx <path>
```

**Note**: `-R` applies to existing content only. New content created afterward
still inherits from the top-level directory's default ACLs.

### Step 7: Verify

```bash
# Check directory ACLs
getfacl <path>

# Check inheritance by creating test content
su -c "touch <path>/testfile" <collaborator>
getfacl <path>/testfile

su -c "mkdir <path>/testdir" <collaborator>
getfacl <path>/testdir

# Test access for each principal
su -c "cat <path>/testfile" <readonly_user>      # should work
su -c "echo x >> <path>/testfile" <readonly_user> # should fail
su -c "ls <path>/" <outsider>                     # should fail

# Test explicit denial if applicable
su -c "ls <path>/" <denied_user>                  # should fail
```

## Permission Patterns

### Full Collaborator (read + write + execute)

```
Access ACL:  u:name:rwx
Default ACL: u:name:rwx
```

On directories: effective rwx (can read, create, delete, traverse).
On regular files: effective rw- (can read and modify, not execute unless chmod'd).
On executables: effective r-x (can read and execute, mask limits write).

### Read-Only / Traversal User

```
Access ACL:  u:name:r-x
Default ACL: u:name:r-x
```

On directories: effective r-x (can list contents and traverse).
On regular files: effective r-- (can read, cannot modify or execute).
On executables: effective r-x (can read and execute, after chmod makes them so).

Cannot create files/directories (no write on directory).
Cannot modify files (no write on files).

### Complete Denial

Two approaches:
1. **No named entry + `other::---`**: User falls through to other class, gets nothing.
2. **Explicit `u:name:---`**: Named entry with no permissions. Useful when other
   class grants some access but a specific user must be excluded.

### Group-Based Access

```
Access ACL:  g:teamname:rwx
Default ACL: g:teamname:rwx
```

All members of `teamname` get rwx (masked by mask). This is more maintainable
than individual user entries when team membership changes frequently.

**Note**: If a user matches both a named user entry and a named group entry,
the named user entry wins (evaluation order).

## Mask Management

### When the Mask Matters

The mask must be set wide enough to allow all needed effective permissions:

- If any named user needs `rwx`, the mask must be at least `rwx`
- If a named user needs only `r-x`, the mask must be at least `r-x`
- The mask also limits the owning group entry (`group::`)

### Mask on Created Files

The file's mask at creation = default_mask AND file_creation_mode:
- Files created with `open(..., 0666)`: mask = default_mask AND rw-
- Directories created with `mkdir(..., 0777)`: mask = default_mask AND rwx
- After `chmod`: mask is explicitly set to the group-class bits

This means setting `default:mask::rwx` is safe — it won't grant unintended
execute on regular files because file creation mode doesn't include execute.

### Recalculating the Mask

If you add/modify named entries, `setfacl` automatically recalculates the mask
to be the union of all named entries and the owning group entry. To prevent
this (and set a specific mask), use `-n` flag:

```bash
setfacl -n -m m::rwx <path>   # set mask explicitly without recalculation
```

## Recursive and Bulk Operations Reference

Quick reference for setfacl operations on existing content:

| Command | Purpose |
|---|---|
| `setfacl -R -m ... <path>` | Apply access ACLs recursively to existing files/dirs |
| `setfacl -R -d -m ... <path>` | Apply default ACLs recursively to existing subdirs only |
| `setfacl -x u:name <path>` | Remove a specific named user entry |
| `setfacl -x g:name <path>` | Remove a specific named group entry |
| `setfacl -b <path>` | Remove ALL extended ACLs (keep base owner/group/other) |
| `setfacl -k <path>` | Remove default ACLs from a directory |
| `setfacl --set=... <path>` | Replace entire ACL atomically (vs `-m` which merges) |
| `setfacl -n -m m::r-x <path>` | Set mask without auto-recalculation |

**Note**: `-R` applies to existing content only. New content created afterward
still inherits from the top-level directory's default ACLs.

## Common Pitfalls

1. **Forgetting default ACLs**: Access ACLs on the directory don't propagate.
   Default ACLs are required for inheritance.

2. **Forgetting setgid**: Without setgid, new files get the creator's primary
   group, not the shared group. This breaks group-based access.

3. **Mask too restrictive**: If the mask is `r--`, named users with `rwx`
   entries only get effective `r--`. Always verify with `getfacl`.

4. **Execute on files vs directories**: The `x` permission means different
   things:
   - On directories: ability to traverse/access contents
   - On files: ability to execute as a program
   - Default ACLs with `r-x` give directories r-x but files only r-- (due
     to creation mode intersection)

5. **Owner bypass**: The file owner always uses `user::` (not masked), even
   if there's a named user entry for them. Named entries matter for
   NON-owner access.

6. **Deleting files**: Write permission on the DIRECTORY is needed to
   create/delete entries. Even if a user can read a file, they can't delete
   it without write+execute on the parent directory.

7. **chmod after setfacl silently breaks ACLs**: As detailed in the
   "chmod ↔ ACL Mask" section, running `chmod` on an ACL'd path modifies
   the mask, not the group entry. Always run chmod before setfacl, or
   re-apply setfacl after any chmod.

8. **Missing sticky bit in multi-writer workspaces**: When several
   collaborators have write access to a shared directory, any can delete
   others' files. Add the sticky bit (mode `3770`) to restrict deletion
   to file owners.

## Adapting to Variant Tasks

When facing a new variant, follow this concrete workflow:

### 1. Extract the Access Policy

Build a table from the task requirements:

| Principal | Type | Required Access | Entry to Set |
|---|---|---|---|
| directory owner | user (owner) | varies | `u::perms` |
| owning group | group (owning) | varies | `g::perms` |
| alice | named user | rwx | `u:alice:rwx` |
| developers | named group | rwx | `g:developers:rwx` |
| runner | named user | r-x | `u:runner:r-x` |
| contractor | named user | denied | `u:contractor:---` |
| everyone else | other | no access | `o::---` |

### 2. Determine Permission Sets

For each principal, determine:
- **On directories**: What rwx combination? (r-x = traverse+list, rwx = full)
- **On files**: What effective rwx? (Remember: files created without x, so `r-x` default → `r--` effective on new files)
- **On executables**: Should the user be able to execute scripts others make executable? (Needs `x` in the ACL entry)

### 3. Compute the Mask

```
mask = union of all permission bits needed by:
  - All named user entries
  - All named group entries  
  - The owning group entry (g::)
```

Set the mask explicitly in default ACLs to this value (usually `rwx`).

### 4. Choose Entry Strategy

- **Use named user entries** when individuals need different permission levels
- **Use named group entries** when all members of a team need the same access
- **Use explicit denial entries** (`u:name:---`) when a user must be blocked despite group membership
- **Rely on `other::---`** when no non-listed users need any access

### 5. Construct and Execute Commands

Build the `setfacl` commands following the General Procedure above. Always:
- Set both access ACLs AND default ACLs on the root directory
- Run `chmod` BEFORE `setfacl` (or re-apply setfacl after chmod)
- Use `setfacl -R` if existing content needs updating

### 6. Verify Systematically

For EACH principal in the policy table, test:
- Can they do what they should? (read/write/traverse/execute as required)
- Can they NOT do what they shouldn't? (write when read-only, access when denied)
- Does inheritance work? Create files and subdirs, check ACLs propagate
- Does deep inheritance work? Test 2+ levels deep
