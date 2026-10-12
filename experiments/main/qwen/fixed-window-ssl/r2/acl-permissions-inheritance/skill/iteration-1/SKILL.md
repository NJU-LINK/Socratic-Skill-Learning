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
chgrp <group> <workspace>
chmod 2770 <workspace>   # setgid + rwx for owner/group, nothing for others
```

- **setgid (2000 bit)**: New files and subdirectories inherit the parent's group ownership, not the creator's primary group. This is essential for group-based collaboration.
- **Base mode 2770**: Owner and group get full access; others get nothing at the traditional permission level.

### 2. Access ACLs (on the directory itself)

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

### 3. Default ACLs (for inheritance)

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

### 4. Subdirectory Inheritance

When a subdirectory is created inside a directory with default ACLs:
- The subdirectory inherits the parent's default ACLs as **both** its access ACLs **and** its own default ACLs.
- This means inheritance propagates to arbitrary depth automatically.
- The setgid bit also propagates, so group ownership is maintained.

### 5. The `chmod` ↔ ACL Mask Interaction

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

### 6. Verification Procedure

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
   chgrp <group> <path>
   chmod 2<owner_perms><group_perms>0 <path>
   ```
   The leading digit is 2 for setgid. Adjust owner/group perms to match the collaboration model.

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

## Common Pitfalls

1. **Forgetting the mask**: If the mask is too restrictive (e.g., `r--`), all named entries are capped at that level regardless of their explicit permissions.

2. **Not setting default ACLs**: Without default ACLs, new children get no ACL entries and fall back to traditional permissions + umask. The collaboration policy won't propagate.

3. **Forgetting setgid**: Without setgid, new items get the creator's primary group, not the collaboration group. This breaks group-based access.

4. **Confusing access ACLs with default ACLs**: Access ACLs control the directory itself. Default ACLs control what children inherit. Both must be set.

5. **Expecting execute on regular files**: Default ACL `r-x` entries do NOT grant execute on regular files created with mode 0666. This is by design — it's how POSIX ACLs differentiate ordinary files from executables.

6. **Others getting access through traditional permissions**: Always explicitly set `other::---` in both access and default ACLs. The base mode `2770` helps but ACLs can override it.

7. **`chmod` on ACL files changes the mask, not the group entry**: A `chmod 644` silently caps all named ACL entries at `r--`. A `chmod g-w` removes write from the mask, degrading all named entries. Use `setfacl -m` for targeted permission changes, or re-set the mask (`setfacl -m m::rwx`) after any `chmod`.

## Spec Variation Dimensions

This skill handles variation along three axes:

- **access_policy_topology**: Different combinations of named users, groups, and denied principals. The method is the same — enumerate all principals, set their ACL entries, ensure the mask covers the union.

- **permission_model**: Different rwx combinations. The creation-mode intersection mechanism works the same way regardless of the specific permission set. For restricted principals, choose the right default ACL entry (e.g., `r--` for read-only, `r-x` for read+traverse, `rw-` for read+write without execute).

- **inheritance_and_group_propagation**: Deeper trees, multiple generations, different creation orders. Default ACLs propagate automatically to arbitrary depth. Setgid ensures group ownership propagates. The only thing to verify is that both mechanisms are in place.
