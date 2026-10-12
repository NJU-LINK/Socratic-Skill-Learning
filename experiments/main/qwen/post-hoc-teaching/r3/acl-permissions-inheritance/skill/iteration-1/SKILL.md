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
3. **Owning group or named group match** → use matching group entry, **masked**
4. **Fall through** → use `other::` (NOT masked)

The first matching class wins. If a user matches a named user entry, group
entries are never consulted for that user.

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

## General Procedure

### Step 1: Analyze Requirements

Identify from the task:
- **Target path**: The shared directory to configure
- **Owner and group**: Who owns the directory and what group controls access
- **Base mode**: The traditional Unix permission bits (often `2770` for
  collaborative workspaces with setgid)
- **Principals and their permissions**: Each user/group and what they need:
  - Full collaborators: typically `rwx`
  - Read-only/traversal users: `r-x` on directories, `r--` effective on files
  - Denied users: either no ACL entry + `other::---`, or explicit `---` entry
- **Inheritance needs**: Whether default ACLs are required and what they
  should contain

### Step 2: Create Directory and Set Base Permissions

```bash
mkdir -p <path>
chown <owner>:<group> <path>
chmod <mode> <path>    # e.g., 2770 for setgid + rwxrwx---
```

The mode `2770` means: setgid (2) + owner rwx (7) + group rwx (7) + others --- (0).

### Step 3: Clear Existing ACLs

```bash
setfacl -b <path>
```

This removes all extended ACL entries, starting clean.

### Step 4: Set Access ACLs on the Directory

Use `setfacl -m` to set multiple entries at once or one at a time:

```bash
# Combined form (recommended for atomicity):
setfacl -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,o::--- <path>
```

Key decisions:
- `u::rwx` — owner gets full access
- `g::rwx` — owning group gets full access (adjust per requirements)
- `u:name:rwx` — named collaborators get full access
- `u:name:r-x` — read-only users get traverse + read (no write)
- `o::---` — others get nothing (adjust per requirements)

**Named group entries**: If access is granted through group membership rather
than individual user entries:
```bash
setfacl -m g:developers:rwx <path>
```

### Step 5: Set Default ACLs for Inheritance

Default ACLs determine what access ACLs newly created children will receive:

```bash
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,o::---,m::rwx <path>
```

**Mask in default ACLs**: Set `m::rwx` (or whatever the maximum needed
permission is) so that named entries are not unnecessarily restricted. The
actual effective permissions on created files will still be limited by the
intersection of this default mask with the file creation mode.

**Important**: Default ACLs should mirror the access ACLs for named entries,
so that the permission policy is consistent across the directory tree.

### Step 6: Verify

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

## Recursive Operations for Existing Content

When fixing permissions on an existing directory tree (not just a fresh one):

```bash
# Apply access ACLs recursively to all existing files/dirs
setfacl -R -m u:alice:rwx,u:bob:rwx <path>

# Apply default ACLs recursively to all existing subdirectories
# (files silently skip default ACLs; only directories get them)
setfacl -R -d -m u:alice:rwx,u:bob:rwx <path>

# Remove a specific ACL entry from a single path
setfacl -x u:name <path>

# Remove all extended ACLs (keep base owner/group/other)
setfacl -b <path>

# Replace the entire ACL atomically (vs -m which merges)
setfacl --set=u::rwx,u:alice:rwx,g::rwx,m::rwx,o::--- <path>

# Remove default ACLs from a directory
setfacl -k <path>
```

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

When facing a new variant of this task family:

1. **Parse the access policy topology**: Identify all principals (users,
   groups) and their required access levels. Map each to the appropriate
   ACL entry type and permission set.

2. **Parse the permission model**: Determine the exact rwx combinations
   needed. Consider whether directory traversal and file execution need
   different treatment. Determine if the mask plays a special role.

3. **Parse the inheritance requirements**: Determine how deep the tree goes,
   whether default ACLs need to propagate through multiple levels, and
   whether setgid is needed for group ownership propagation.

4. **Construct the ACL commands**: Build setfacl commands that implement
   the policy. Always set both access and default ACLs. Verify with
   getfacl and functional tests.

5. **Test edge cases**: Verify that:
   - Each principal can do what they should
   - Each principal cannot do what they shouldn't
   - Inheritance works for both files and subdirectories
   - Deeper levels maintain correct permissions
