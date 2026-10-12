---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspaces with correct inheritance
  via default ACLs and setgid group propagation. Handles arbitrary
  access-policy topologies (named users, groups, denied principals),
  varied permission models (rwx combinations, mask control), and deep
  inheritance trees where newly created files and subdirectories must
  inherit the intended access pattern.
---

# ACL Permissions Inheritance

## Overview

This skill configures Linux POSIX ACLs on a shared directory so that:

- Named users and/or groups receive specified access levels.
- Additional principals may receive restricted access (e.g., read-only, traverse-only).
- All other users are denied.
- Permissions propagate correctly to newly created files and subdirectories at any depth.

## Core Mechanisms

### 1. Directory Setup: Ownership, Setgid, Base Mode

```bash
mkdir -p <workspace>
chown <owner>:<group> <workspace>   # set both owner user and group
chmod 2770 <workspace>   # setgid + rwx for owner/group, nothing for others
```

- **Owner user**: Use `chown <user>:<group>` to set both the owner user and group. If the task doesn't specify an owner, root is typical. The `user::` ACL entry applies to whoever owns the directory, not a specific username.
- **setgid (2000 bit)**: New files and subdirectories inherit the parent's group ownership, not the creator's primary group. This is essential for group-based collaboration.
- **Base mode 2770**: Owner and group get full access; others get nothing at the traditional permission level.
- **Parent directory permissions**: Ensure parent directories (e.g., `/srv`) allow traversal (at least `--x` for relevant users). If `/srv` is `700 root:root`, then even a correctly configured `/srv/shared` won't be accessible to non-root users.

### 2. ACL Evaluation Order

POSIX ACLs are evaluated in this strict order:

1. **File owner** → `user::` entry (the owner of the file/directory). No mask applied.
2. **Named users** → If a `u:<name>:` entry exists for the process's user, that entry determines access. The entry is ANDed with the ACL mask. Evaluation stops here.
3. **Groups (union semantics)** → Collect ALL group entries that match the process:
   - The owning group `group::` entry (if the process is a member of that group)
   - Any matching named group entries `g:<name>:`
   - **OR (union)** all their permission bits together
   - **AND** the result with the ACL mask
   - That final value determines access for the group class
4. **Others** → `other::` entry. No mask applied.

**Critical implications**:

- **Named user entries override group membership**: If alice is in the `editors` group with `group::rwx`, but you set `u:alice:---`, alice is denied access despite her group membership. This is essential for policies that need to deny specific users who would otherwise have access through group membership.

- **Group evaluation is union, not first-match**: If a user is in both the `editors` group (`group::rwx`) AND a named group `g:viewers:r--`, the effective group permission is `(rwx | r--) & mask = rwx & mask`. The named group's restrictive entry does NOT override the owning group's broader entry — they're unioned. Only if NO group entry matches does evaluation fall through to `other::`.

- **Mask asymmetry**: The mask applies to named users (step 2) and groups (step 3), but NOT to the file owner (step 1) or others (step 4). This means `user::rwx` and `other::---` are never restricted by the mask.

**Example**: To deny alice access while keeping group access for other editors:
```bash
setfacl -m u:alice:--- <workspace>   # alice denied (named entry checked at step 2)
# group::rwx still applies to other editors members at step 3
```

### 3. Access ACLs (on the directory itself)

Control who can access the directory right now:

```bash
# Full collaborators
setfacl -m u:<user>:rwx <workspace>
setfacl -m g:<group>:rwx <workspace>   # if group-based collaboration

# Restricted principals
setfacl -m u:<user>:r-x <workspace>    # traverse + read, no write

# Deny others
setfacl -m o::--- <workspace>

# Ensure mask allows full permissions for named entries
setfacl -m m::rwx <workspace>
```

**Mask importance**: The ACL mask acts as an upper bound on permissions for all named user entries, named group entries, and the owning group entry. If the mask is too restrictive, even explicit rwx entries become ineffective. Always set the mask to at least the union of all desired named-entry permissions.

### 4. Default ACLs (for inheritance)

Default ACLs determine what ACL entries newly created children inherit. They are the key to making permissions propagate without manual intervention.

```bash
setfacl -d -m u::rwx <workspace>          # owner of new items gets rwx
setfacl -d -m g::rwx <workspace>          # owning group gets rwx
setfacl -d -m u:<collab1>:rwx <workspace> # each collaborator
setfacl -d -m u:<collab2>:rwx <workspace>
setfacl -d -m u:<restricted>:r-x <workspace>  # restricted principal
setfacl -d -m o::--- <workspace>          # others get nothing
setfacl -d -m m::rwx <workspace>          # mask allows full named-entry perms
```

**Critical insight — creation mode intersection**: When a file or directory is created, the effective inherited ACL is the *intersection* of the default ACL and the creation mode:

| Created by | Typical mode | Effect on inherited ACL |
|---|---|---|
| Regular file (`open()`, `echo >`, `touch`) | 0666 (no execute) | Named entries lose execute bit. `r-x` becomes `r--`. |
| Script made executable (`chmod +x`) | 0755+ | Execute bit present. `r-x` stays `r-x`. |
| Directory (`mkdir`) | 0777 | Full mode. `r-x` stays `r-x`. |

This means a single `default:user:<name>:r-x` entry automatically provides the right behavior:
- Can read ordinary files (r-- effective)
- Can execute scripts that collaborators explicitly make executable (r-x effective)
- Can traverse directories (r-x effective)
- Cannot write to anything (no w bit)

### 5. Subdirectory Inheritance

When a subdirectory is created inside a directory with default ACLs:
- The subdirectory inherits the parent's default ACLs as **both** its access ACLs **and** its own default ACLs.
- This means inheritance propagates to arbitrary depth automatically.
- The setgid bit also propagates, so group ownership is maintained.

### 6. The `chmod` ↔ ACL Mask Interaction

This is a critical and subtle mechanism that causes silent policy breakage:

**When `chmod` is applied to a file or directory that has ACLs:**
- `chmod u:<perms>` → sets the ACL `user::` (owner) entry
- `chmod g:<perms>` → sets the ACL **mask** entry (NOT `group::`!)
- `chmod o:<perms>` → sets the ACL `other::` entry

The mask controls the effective ceiling for ALL named user entries, named group entries, AND the owning group entry. So any `chmod` that modifies the group-class bits silently changes the effective permissions of every named ACL entry.

**Concrete examples of silent breakage:**

| chmod command | Effect on mask | Consequence |
|---|---|---|
| `chmod 644 file` | mask → `r--` | All named entries (alice:rwx, bob:rwx) become effective `r--` only. Collaborators lose write access. |
| `chmod g-w file` | mask → loses `w` | Named entries lose write. Collaborators can read but not modify. |
| `chmod 755 dir` | mask → `r-x` | Named entries capped at `r-x`. Collaborators lose write on the directory. |
| `chmod +x file` | mask gains `x` | Usually harmless (adds execute ceiling), but also sets `other::` execute. |

**Why this matters for family variants:**
1. If a task requires collaborators to run `chmod 644` on files (e.g., for a web server), that `chmod` sets the mask to `r--`, silently breaking all collaborator write access through ACLs.
2. If a test or script inside the workspace does `chmod` operations, it can unintentionally degrade the ACL policy.
3. The `other::` entry is also affected — `chmod 644` sets `other::r--`, potentially granting read access to non-collaborators.

**Mitigation strategies:**
- **Prefer `setfacl -m`** for permission changes on ACL-managed files instead of `chmod`. `setfacl` modifies specific ACL entries without touching the mask unless you explicitly target it.
- **Re-set the mask after `chmod`**: If `chmod` must be used, follow up with `setfacl -m m::<desired_mask> <path>` to restore the intended mask.
- **Document the risk**: If the task involves file lifecycle operations where collaborators or scripts will run `chmod`, note this interaction and plan for mask restoration.

**The directory-level ACL policy is still protected**: Directory `chmod` is rare in practice, and the default ACLs on the parent directory ensure new children start with the correct mask. The risk is primarily for existing files that get `chmod`'d after creation.

### 7. Verification Procedure

After configuration, verify with:

```bash
# Check ACL state
getfacl <workspace>

# Test as each principal
su -s /bin/bash -c "<command>" <user>

# Test inheritance by creating and inspecting children
su -s /bin/bash -c "touch <workspace>/testfile" <collaborator>
getfacl <workspace>/testfile
su -s /bin/bash -c "mkdir <workspace>/testdir" <collaborator>
getfacl <workspace>/testdir

# Test restricted principal behavior
su -s /bin/bash -c "cat <workspace>/testfile" <restricted>    # should work
su -s /bin/bash -c "touch <workspace>/newfile" <restricted>   # should fail
```

## General Method for Arbitrary Policy Topologies

Given a task specifying:
- A workspace path
- A collaborating group
- Named users/groups with specified access levels
- Restricted principals with different access levels
- An "everyone else denied" requirement

**Step-by-step**:

1. **Identify all principals** and their required permission sets:
   - Collaborators: typically `rwx` (full access)
   - Restricted users: determine exact rwx needed (e.g., `r-x` for read+traverse)
   - Others: `---` (no access)

2. **Set up the directory**:
   ```bash
   mkdir -p <path>
   chown <owner>:<group> <path>
   chmod 2<owner_perms><group_perms>0 <path>
   ```
   The leading digit is 2 for setgid. Adjust owner/group perms to match the collaboration model. If the task doesn't specify an owner, use `root`.

3. **Set access ACLs** for every principal that needs non-base-permission access:
   ```bash
   for each named user <u> with perms <p>:
       setfacl -m u:<u>:<p> <path>
   for each named group <g> with perms <p>:
       setfacl -m g:<g>:<p> <path>
   setfacl -m o::--- <path>
   ```

4. **Set the mask** to the union of all named entry permissions:
   ```bash
   setfacl -m m::rwx <path>   # or whatever the union requires
   ```

5. **Set default ACLs** mirroring the access policy:
   ```bash
   setfacl -d -m u::rwx <path>
   setfacl -d -m g::rwx <path>
   for each access ACL entry, create a corresponding default entry:
       setfacl -d -m u:<u>:<p> <path>
       setfacl -d -m g:<g>:<p> <path>
   setfacl -d -m o::--- <path>
   setfacl -d -m m::rwx <path>
   ```

6. **Verify** inheritance works at multiple depths and for both files and directories.

## Idempotency and Cleanup

When working with pre-existing directories or re-running the setup:

- **`setfacl -b <path>`**: Removes ALL ACLs (both access and default) from the specified path. The directory reverts to basic POSIX permissions. Use this to clean up stale ACLs before applying a new policy.
- **`setfacl -k <path>`**: Removes only the default ACLs, leaving access ACLs intact. Use this when you need to reset inheritance without affecting the directory's own permissions.
- **`setfacl -R -m <entries> <path>`**: Recursively applies ACL modifications to all files and subdirectories under `<path>`. Use this when you need to update ACLs on existing content after a policy change.

**Example: Clean re-application**
```bash
# Remove all existing ACLs
setfacl -b /srv/shared

# Re-apply the complete policy
setfacl -m u:alice:rwx,u:bob:rwx,u:runner:r-x,o::---,m::rwx /srv/shared
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,o::---,m::rwx /srv/shared
```

**Note**: `setfacl -b` preserves the setgid bit and traditional permissions. It only removes ACL entries.

## Additional Mechanisms for Family Variants

### Sticky Bit for Delete Protection

In some shared workspace scenarios, you may need to prevent users from deleting each other's files even though they have write permission on the directory. The **sticky bit** (mode 1000) provides this protection:

```bash
chmod +t <workspace>   # Add sticky bit (mode becomes 3770 if setgid is also set)
```

With the sticky bit set, only the file owner, directory owner, or root can delete or rename files in the directory. This is useful for collaboration scenarios where multiple users need write access but shouldn't be able to delete each other's work.

**When to use**: If the task mentions preventing accidental deletion, protecting shared files, or scenarios similar to `/tmp`, consider adding the sticky bit.

### File Owner vs Named User Entry

Remember the ACL evaluation order: if a process is the file owner, the `user::` entry (step 1) is used, NOT any named user entry (step 2). This means:

- If alice owns a file and there's a `u:alice:r--` entry, alice still gets access based on `user::` (typically `rw-` for files), not the restrictive named entry.
- Named user entries are only evaluated for non-owners.

This is important when reasoning about access control for files created by collaborators.

## Common Pitfalls

1. **Forgetting the mask**: If the mask is too restrictive (e.g., `r--`), all named entries are capped at that level regardless of their explicit permissions.

2. **Not setting default ACLs**: Without default ACLs, new children get no ACL entries and fall back to traditional permissions + umask. The collaboration policy won't propagate.

3. **Forgetting setgid**: Without setgid, new items get the creator's primary group, not the collaboration group. This breaks group-based access.

4. **Confusing access ACLs with default ACLs**: Access ACLs control the directory itself. Default ACLs control what children inherit. Both must be set.

5. **Expecting execute on regular files**: Default ACL `r-x` entries do NOT grant execute on regular files created with mode 0666. This is by design — it's how POSIX ACLs differentiate ordinary files from executables.

6. **Others getting access through traditional permissions**: Always explicitly set `other::---` in both access and default ACLs. The base mode `2770` helps but ACLs can override it.

7. **`chmod` on ACL files changes the mask, not the group entry**: A `chmod 644` silently caps all named ACL entries at `r--`. A `chmod g-w` removes write from the mask, degrading all named entries. Use `setfacl -m` for targeted permission changes, or re-set the mask (`setfacl -m m::rwx`) after any `chmod`.

8. **Parent directory must allow traversal**: Even a perfectly configured `/srv/shared` is inaccessible if `/srv` is `700 root:root`. Ensure all ancestor directories grant at least execute (`--x`) to the users who need to reach the workspace.

9. **Group evaluation is union, not first-match**: If a user matches multiple group entries (e.g., `group::rwx` and `g:viewers:r--`), the effective permission is the UNION of all matching entries, then masked. A restrictive named group entry does NOT override a permissive owning group entry.

10. **Named user entries override group membership**: A `u:alice:---` entry denies alice access even if she is a member of a group with `group::rwx`. Named user evaluation (step 2) happens before group evaluation (step 3).

11. **File owner bypasses named user entry**: If alice owns a file, her access is determined by `user::` (step 1), not `u:alice:` (step 2). A restrictive named user entry on alice's own file does NOT restrict alice — she still gets full owner access.

12. **`setfacl -b` removes everything**: The `-b` flag removes ALL ACLs (access and default) and the mask entry. Use it for clean re-application, but be aware it strips inherited default ACLs from children too if used with `-R`.

13. **Default ACLs auto-inherit on creation**: When you create a new directory inside a parent with default ACLs, the child automatically inherits those defaults as both access ACLs and its own default ACLs. You don't need to re-apply ACLs to newly created children.

14. **Filesystem must support ACLs**: POSIX ACLs require filesystem support. Most modern Linux filesystems (ext3/4, xfs, btrfs) support ACLs, but they may need to be enabled at mount time with the `acl` option. If `setfacl` returns "Operation not supported", check the filesystem mount options with `mount | grep acl` or `tune2fs -l /dev/<device> | grep acl`.

## Spec Variation Dimensions

This skill handles variation along three axes:

- **access_policy_topology**: Different combinations of named users, groups, and denied principals. The method is the same — enumerate all principals, set their ACL entries, ensure the mask covers the union.

- **permission_model**: Different rwx combinations. The creation-mode intersection mechanism works the same way regardless of the specific permission set. For restricted principals, choose the right default ACL entry (e.g., `r--` for read-only, `r-x` for read+traverse, `rw-` for read+write without execute).

- **inheritance_and_group_propagation**: Deeper trees, multiple generations, different creation orders. Default ACLs propagate automatically to arbitrary depth. Setgid ensures group ownership propagates. The only thing to verify is that both mechanisms are in place.
