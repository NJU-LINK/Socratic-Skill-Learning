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

### 1. POSIX ACL Evaluation Algorithm

When a process accesses a file, the kernel checks permissions in this **exact
order** — first match wins:

1. **File owner?** → Use `user::` entry. Done. (NOT affected by mask.)
2. **Named user entry matches process UID?** → Use that `user:name:` entry,
   intersected with `mask::`. Done.
3. **Owning group matches process GID or supplementary groups?** → Use
   `group::` entry, intersected with `mask::`. Done.
4. **Named group entry matches process GID or supplementary groups?** → Use
   that `group:name:` entry, intersected with `mask::`. Done. (If multiple
   group entries match, the union of their permissions is used, then masked.)
5. **Fall through** → Use `other::` entry. Done. (NOT affected by mask.)

**Critical implication**: A named user entry (`user:runner:r-x`) takes
precedence over any group-based entry, even if the user belongs to a group
that has a different ACL entry. This is how you give a user in the owning
group different permissions from the rest of the group.

### 2. The ACL Mask (Critical)

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

### 3. Access ACLs vs Default ACLs

- **Access ACLs** control permissions on the directory/file itself
- **Default ACLs** (only valid on directories) define the ACL template that
  newly created children inherit
- Both must be set on the shared root directory
- Default ACLs propagate recursively: subdirectories inherit the default ACLs
  as both their access ACLs and their own default ACLs

**Inheritance mechanism**: When a new file/directory is created:
- The new item's access ACL = default ACL of parent ∩ creation mode
- For files: creation mode is typically 0666 (no execute bits)
- For directories: creation mode is typically 0777 (all bits)
- The new item's default ACL = parent's default ACL (directories only)

### 4. Setgid for Group Propagation

`chmod g+s` (or mode 2xxx) on a directory causes all new files and
subdirectories to inherit the directory's group ownership, regardless of the
creator's primary group. This works in tandem with default ACLs:
- Setgid ensures `group::` entries apply to the right group
- Default ACLs ensure named user/group entries propagate

### 5. chmod Behavior Under ACLs (Subtle!)

When a file has ACLs (indicated by `+` in `ls -l`), `chmod` behaves
differently than without ACLs:

- `chmod u:...` → modifies `user::` entry
- `chmod g:...` → modifies the **mask** entry (NOT `group::`)
- `chmod o:...` → modifies `other::` entry

This means `chmod +x` on a file with ACLs will:
- Add execute to `user::`
- Add execute to `mask::` (which may expand effective permissions for named entries!)
- Add execute to `other::`

**Practical consequence**: If a collaborator runs `chmod +x script.sh` in a
shared directory, the `other::` entry may gain execute. This is safe only if
the directory itself blocks `other` from entering (which `other::---` on the
parent directory ensures). The `mask::` expansion is also usually fine since
the mask was already `rwx`.

**Best practice**: Use `chmod u+x` or `setfacl -m u:name:rwx` instead of
bare `chmod +x` when you want precise control. But for the common case of
"make this script executable," `chmod +x` is fine as long as directory-level
`other::---` blocks outsiders.

### 6. Sticky Bit for Shared-Write Directories

When multiple users can create files in the same directory (all have `w` on
the directory), any of them can normally delete any file in that directory
(because deletion is controlled by directory write permission, not file
permission). The **sticky bit** (`chmod +t`, mode `x770` → `x+t`) prevents
this: only the file owner, directory owner, or root can delete/rename files.

Consider adding the sticky bit when:
- Multiple collaborators have write access to the same directory
- You want to prevent accidental or malicious deletion of others' files
- The task mentions "shared workspace" with multiple writers

Set with: `chmod +t <dir>` or include in the mode: `chmod 3770 <dir>`
(the `3` = setgid + sticky).

## Generalized Procedure

### Step 1: Analyze Requirements

Map the task requirements to ACL entries using this decision process:

1. **Identify the directory path, owner, and owning group**
2. **Identify full-access principals** (need rwx on dirs, rw on files):
   - These get `user:name:rwx` entries
3. **Identify read-only/traverse principals** (need r-x on dirs, r-- on files):
   - These get `user:name:r-x` entries
   - r-x on directories = can list, enter, and pass through
   - r-x on files = can read and execute (but files are created without x)
4. **Identify denied principals**:
   - Specific users who must be blocked: `user:name:---`
   - Everyone else: `other::---`
5. **Calculate the mask**: Union of all named entry permissions
   - If anyone needs rwx → mask must be rwx
6. **Determine if sticky bit is needed** (multiple writers sharing a dir)

### Step 2: Create Directory and Set Base Permissions

```bash
mkdir -p <path>
chown <owner>:<group> <path>
chmod 2770 <path>   # setgid + rwx for owner and group, nothing for other
# Or: chmod 3770 <path>  # if sticky bit is also needed
```

The `2` prefix sets the setgid bit. Mode `770` gives rwx to owner and group.

### Step 3: Set Access ACLs

```bash
# Set all named user entries and mask in one command
setfacl -m u:<user1>:rwx,u:<user2>:rwx,u:<user3>:r-x,m::rwx,o::--- <path>
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
- [ ] If sticky bit needed: check for 't' in other execute position

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

6. **chmod g+ modifies the mask, not group::**: Under ACLs, `chmod g:rwx`
   sets the mask to rwx, not the owning group entry. Use `setfacl` for
   precise control over the owning group entry.

7. **Not cleaning up test artifacts**: Always remove test files/directories
   created during verification. The task says "Do not pre-create test files."

## Adapting to Different Topologies

### Multiple collaborating groups
Add named group entries: `setfacl -m g:groupname:rwx <path>`
Include in defaults: `setfacl -d -m g:groupname:rwx <path>`

### Denying specific users beyond "other"
Give that user a named entry with `---`: `setfacl -m u:baduser:--- <path>`
Named user entries take precedence over group entries (per the evaluation
algorithm), so this overrides any group-based access the user might have.

### Deep directory trees
Default ACLs automatically propagate to all depths. No special configuration
needed beyond setting defaults on the root shared directory.

### Different permission levels per user
Simply assign different permission bits to each named user entry:
- Full collaborator: `u:alice:rwx`
- Read-only reviewer: `u:reviewer:r-x`
- Write-only logger: `u:logger:-wx` (can create files but not read others')
- Adjust mask to be the union of all needed permissions

### Pre-existing directory trees
Use `-R` (recursive) to apply ACLs to existing content:
```bash
setfacl -R -m u:name:rwx <path>          # access ACLs recursively
setfacl -R -d -m u:name:rwx <path>       # default ACLs on all subdirs
```
Note: Default ACLs (`-d`) only apply to directories, so `-R -d` silently
skips files.

### Varying the permission model
The spec mentions "cases where directory traversal and file execution
requirements differ." Handle this with:
- Directory-level entries control traversal (need `x` on directories)
- File-level entries control execution (need `x` on files)
- Default ACLs with `r-x` give both: directories get `r-x`, files get
  effective `r--` (no execute) until explicitly chmod'd
- If you need files to be executable by default (unusual), you'd need to
  explicitly `chmod +x` after creation, or use a different creation mode
