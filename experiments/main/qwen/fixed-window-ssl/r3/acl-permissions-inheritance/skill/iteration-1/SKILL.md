---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux for shared workspace directories with
  per-principal access control, correct mask handling, and inheritance
  via default ACLs and setgid group propagation. Handles arbitrary mixes
  of named users and groups with different permission levels, read-only
  collaborators, and multi-generation directory trees.
---

# ACL Permissions Inheritance

## Overview

This skill configures Linux POSIX ACLs (via `setfacl`/`getfacl`) on shared
directories so that:

- Named users and groups get precisely the permissions they need
- Permissions inherit correctly to newly created files and subdirectories
- The ACL mask is set correctly to avoid accidentally restricting collaborators
- Setgid ensures group ownership propagates to all descendants

## Core Concepts

### 1. The ACL Mask (Critical)

The `mask` entry defines the **maximum effective permissions** for:
- The owning group (`group::` entry)
- All named user entries (`user:name:...`)
- All named group entries (`group:name:...`)

The mask does **NOT** affect:
- `user::` (the owning user)
- `other::`

**Rule**: Set the mask to the **union** of all permissions any named entry or
the owning group needs. Individual restrictions come from each entry's own
permission bits, not from the mask.

Example: If alice needs `rwx` and runner needs `r-x`, set `mask::rwx`.
Alice gets effective `rwx` (rwx ∩ rwx = rwx). Runner gets effective `r-x`
(r-x ∩ rwx = r-x). A common mistake is setting mask to `r-x` to "restrict"
runner — but that would also restrict alice to `r-x` effective.

### 2. Access ACLs vs Default ACLs

- **Access ACLs** control permissions on the directory itself
- **Default ACLs** (only valid on directories) define the ACL template that
  newly created children inherit
- Both must be set on the shared root directory
- Default ACLs propagate recursively: subdirectories inherit the default ACLs
  as both their access ACLs and their own default ACLs

### 3. File Creation vs Directory Creation

When a process creates a file, the kernel applies the requested mode (typically
0666 for regular files, 0777 for directories) ANDed with the default ACL:
- **Regular files**: Created without execute bits (mode 0666 base). The default
  ACL's execute bits are masked by the creation mode, so named user entries
  like `rwx` become effective `rw-` on new files. This is correct behavior —
  scripts must be explicitly made executable with `chmod +x`.
- **Directories**: Created with all bits (mode 0777 base), so default ACL
  permissions including execute are fully inherited.

### 4. Setgid for Group Propagation

`chmod g+s` (or mode 2xxx) on a directory causes all new files and
subdirectories to inherit the directory's group ownership, regardless of the
creator's primary group. This works in tandem with default ACLs:
- Setgid ensures `group::` entries apply to the right group
- Default ACLs ensure named user/group entries propagate

## Generalized Procedure

### Step 1: Analyze Requirements

Map the task requirements to ACL entries:

| Requirement | ACL Entry | Notes |
|---|---|---|
| Owner access | `user::rwx` | Usually root or a service account |
| Collaborators (full) | `user:name:rwx` | Named user entries |
| Read-only users | `user:name:r-x` | r-x allows traverse + read + execute |
| Collaborating group | `group::rwx` | Owning group entry |
| Everyone else | `other::---` | No access |
| Mask | `mask::rwx` | Union of all named/group permissions needed |

**Key decisions:**
- Who needs full access (rwx)?
- Who needs read-only/traverse access (r-x)?
- Who must be denied (other::---)?
- What group owns the directory?

### Step 2: Create Directory and Set Base Permissions

```bash
mkdir -p <path>
chown <owner>:<group> <path>
chmod 2770 <path>   # setgid + rwx for owner and group, nothing for other
```

The `2` prefix sets the setgid bit. Mode `770` gives rwx to owner and group.

### Step 3: Set Access ACLs

```bash
# Set all named user entries at once
setfacl -m u:<user1>:rwx,u:<user2>:rwx,u:<user3>:r-x <path>

# Explicitly set the mask to the union of all needed permissions
setfacl -m m::rwx <path>

# Ensure other has no access
setfacl -m o::--- <path>
```

**Important**: When adding entries one at a time, setfacl auto-recalculates
the mask. Set the mask explicitly last if you need precise control, or set
everything in one command.

### Step 4: Set Default ACLs for Inheritance

```bash
setfacl -d -m u::rwx,g::rwx,u:<user1>:rwx,u:<user2>:rwx,u:<user3>:r-x,m::rwx,o::--- <path>
```

This ensures every new file and subdirectory inherits:
- The same named user entries
- The same mask
- The same other::--- restriction
- Default ACLs propagate to subdirectories (so inheritance continues recursively)

### Step 5: Verify

```bash
# Check the full ACL listing
getfacl <path>

# Test with different users
su -s /bin/sh <user> -c "touch <path>/testfile"   # Should succeed/fail as expected
su -s /bin/sh <user> -c "ls <path>/"              # Should succeed/fail as expected
su -s /bin/sh <user> -c "cat <path>/testfile"     # Read test
```

**Verification checklist:**
- [ ] Named users with full access can create, read, write, delete
- [ ] Named users with read-only can read and traverse but not create/write/delete
- [ ] Outside users cannot access anything
- [ ] New files inherit correct ACLs (check with getfacl)
- [ ] New subdirectories inherit correct ACLs AND default ACLs
- [ ] Setgid is set (check for 's' in group execute position of ls -l)
- [ ] Group ownership propagates to new items

## Common Pitfalls

1. **Mask too restrictive**: Setting `mask::r-x` to "protect" against writers
   also blocks collaborators' write access. Always set mask to the union.

2. **Forgetting default ACLs**: Access ACLs only affect the directory itself.
   Without default ACLs, new children get permissions from the creating
   process's umask, not from the parent's ACLs.

3. **Forgetting setgid**: Without setgid, new items get the creator's primary
   group, not the shared group. This breaks group-based access.

4. **Confusing group:: with named group entries**: `group::rwx` is the owning
   group entry (affected by mask). `group:editors:rwx` is a named group entry
   (also affected by mask). They are different entries.

5. **Execute on files vs directories**: For a read-only user to traverse a
   directory, they need execute on that directory. For them to run a script,
   they need execute on the file. Default ACLs with `r-x` handle both:
   directories get full `r-x`, files get effective `r--` (due to 0666 creation
   mode) until someone explicitly adds execute.

## Adapting to Different Topologies

### Multiple collaborating groups
Add named group entries: `setfacl -m g:groupname:rwx <path>`
Include in defaults: `setfacl -d -m g:groupname:rwx <path>`

### Denying specific users beyond "other"
Use explicit deny entries (note: POSIX ACLs don't have explicit deny —
instead, simply don't grant permissions, and rely on `other::---`):
- If a specific user must be denied while others in the same group have access,
  give that user a named entry with `---`: `setfacl -m u:baduser:--- <path>`
- Named user entries take precedence over group entries, so this overrides
  any group-based access.

### Deep directory trees
Default ACLs automatically propagate to all depths. No special configuration
needed beyond setting defaults on the root shared directory.

### Different permission levels per user
Simply assign different permission bits to each named user entry:
- Full collaborator: `u:alice:rwx`
- Read-only reviewer: `u:reviewer:r-x`
- Write-only logger: `u:logger:-wx` (can create files but not read others')
- Adjust mask to be the union of all needed permissions
