---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspaces with correct inheritance
  semantics. Covers setgid group propagation, default ACLs for permission
  inheritance to descendants, mask-based effective permission calculation,
  and the interaction between creation-mode bits and inherited ACL masks.
---

# ACL Permissions Inheritance

## Core Mechanisms

### 1. Default ACLs and Inheritance

When a directory has **default ACLs**, every new file or subdirectory created
inside it inherits entries from those defaults. The inheritance rules are:

- **Subdirectories** inherit the default ACL entries as both their access ACL
  **and** as their own default ACLs (so inheritance propagates recursively).
- **Regular files** inherit the default ACL entries as their access ACL only
  (files cannot have default ACLs).

### 2. The Mask–Creation-Mode Intersection (Critical)

Inherited named user/group entries are copied **verbatim** from the default
ACL. However, the inherited **mask** is the bitwise AND of:

- The `default:mask::` entry on the parent directory
- The creation mode from the syscall (typically `0666` for files, `0777` for
  directories)

This means:

| Default entry     | New file (mode 0666)  | New directory (mode 0777) |
|-------------------|-----------------------|---------------------------|
| mask inherited    | mask = default ∩ 0666 | mask = default ∩ 0777     |
| `mask::rwx`       | effective mask: `rw-` | effective mask: `rwx`     |
| `user:X:r-x`      | entry=r-x, eff=`r--`  | entry=r-x, eff=`r-x`     |
| `user:X:rwx`      | entry=rwx, eff=`rw-`  | entry=rwx, eff=`rwx`     |

**This is the key mechanism** for differentiating file vs directory access
without separate configuration. A single `user:runner:r-x` default entry
naturally gives runner read-only on files but read+traverse on directories.

### 3. Mask = Group-Class Bits

When ACLs are present, the traditional group permission bits in `ls -l`
output represent the **ACL mask**, not `group::`. Therefore:

- `chmod g+x file` → sets mask to include execute → unlocks execute for all
  named users/groups whose entry includes `x`
- `chmod +x file` → sets execute on user, mask (group-class), AND other
  → may unintentionally grant execute to `other`
- **Best practice**: collaborators should use `chmod g+x` (not `chmod +x`)
  to make scripts executable, preserving `other::---`

### 4. Setgid for Group Propagation

`chmod g+s` (or `chmod 2xxx`) on a directory causes all new files and
subdirectories created within it to inherit the directory's group ownership,
regardless of the creator's primary group. This is essential for shared
workspaces where multiple users create content.

## General Procedure

### Step 1: Create Groups and Users

```bash
# Idempotent group creation
getent group <groupname> &>/dev/null || groupadd <groupname>

# Users who are collaborators (members of the shared group)
for u in <collaborator1> <collaborator2>; do
  id "$u" &>/dev/null || useradd -m "$u"
  usermod -aG <groupname> "$u"
done

# Users with restricted access (NOT in the shared group)
for u in <restricted_user>; do
  id "$u" &>/dev/null || useradd -m "$u"
done
```

### Step 2: Create the Shared Directory

```bash
mkdir -p <path>
chown <owner>:<groupname> <path>
chmod 2770 <path>   # setgid + rwx for owner and group, nothing for others
```

**Note on umask**: `chmod` after `mkdir` is safe because `chmod` is not
affected by umask. Always explicitly `chmod` after `mkdir` rather than
relying on `mkdir -m`.

### Step 3: Set Access ACLs on the Directory

Grant the required permissions to each principal on the directory itself:

```bash
# Full-access collaborators
setfacl -m u:<collaborator>:rwx <path>

# Restricted users (e.g., read + traverse only)
setfacl -m u:<restricted_user>:r-x <path>

# Deny others
setfacl -m o::--- <path>
```

### Step 4: Set Default ACLs for Inheritance

Mirror the access policy into default ACLs so it propagates to descendants:

```bash
# Owner of new objects
setfacl -d -m u::rwx <path>

# Named users — same permissions as access ACL
setfacl -d -m u:<collaborator>:rwx <path>
setfacl -d -m u:<restricted_user>:r-x <path>

# Owning group
setfacl -d -m g::rwx <path>

# Mask — must be set to the maximum permissions any named entry needs
# (typically rwx; the creation-mode intersection handles the rest)
setfacl -d -m m::rwx <path>

# Others — deny
setfacl -d -m o::--- <path>
```

### Step 5: Verify

```bash
getfacl <path>
```

Confirm both access and default sections contain all expected entries.
Then test inheritance:

```bash
# Create a test file and check inherited ACLs
su - <collaborator> -c "touch <path>/testfile"
getfacl <path>/testfile
# Verify mask is rw- (from 0666 ∩ rwx) and effective permissions are correct

# Create a test directory and check inherited ACLs + default propagation
su - <collaborator> -c "mkdir <path>/testdir"
getfacl <path>/testdir
# Verify mask is rwx (from 0777 ∩ rwx) and defaults are inherited

# Test restricted user behavior
su - <restricted_user> -c "cat <path>/testfile"       # should work (read)
su - <restricted_user> -c "echo x >> <path>/testfile"  # should fail (no write)
su - <restricted_user> -c "touch <path>/newfile"       # should fail (no dir write)

# Test outsider denial
su - <outsider> -c "ls <path>/"                        # should fail

# Clean up test artifacts
rm -f <path>/testfile
rm -rf <path>/testdir
```

## Design Patterns for Common Topologies

### Pattern: Collaborators + Read-Only Traverser

- Collaborators: `user:X:rwx` in both access and default ACLs
- Traverser: `user:Y:r-x` in both access and default ACLs
- The mask intersection naturally gives traverser `r--` on files and `r-x` on directories
- When a collaborator does `chmod g+x script.sh`, the mask gains `x`,
  making the traverser's effective permissions `r-x` on that file

### Pattern: Multiple Groups with Different Access Levels

- Use `group:X:rwx` and `group:Y:r-x` entries in both access and default ACLs
- Set mask to `rwx` to allow full effective permissions for the most-privileged group
- Named group entries follow the same mask intersection rules as named user entries

### Pattern: Explicit Denials Beyond Others

- POSIX ACLs don't have explicit "deny" entries — denial comes from absence
  of permission in all matching entries + `other::---`
- To deny a specific user, simply don't grant them any named entry and set
  `other::---` (or rely on base group permissions)
- If a user is in the owning group but should have reduced access, use a
  named user entry with restricted permissions (named user entries take
  precedence over group entries)

## Recursive ACL Application to Existing Trees

When applying ACLs to a pre-existing directory tree (not built from scratch),
use `setfacl -R` for recursive application:

```bash
# Apply access ACLs recursively to all existing files and directories
setfacl -R -m u:<user>:<perms> <path>

# Apply default ACLs recursively to all existing directories
# (files cannot have default ACLs, so -R -d only affects directories)
setfacl -R -d -m u:<user>:<perms> <path>
```

**Critical caveats:**

1. **Mask auto-recalculation per file**: `setfacl -R -m` recalculates the mask
   independently for each file and directory. The mask becomes the union of all
   group-class entries on that specific inode. This means different files may
   end up with different masks depending on their existing `group::` permissions.

2. **Setgid must be set separately**: Default ACLs do NOT propagate group
   ownership — only setgid does. When applying ACLs to an existing tree, you
   must also ensure setgid is set on directories:
   ```bash
   # Set setgid on all directories in the tree
   find <path> -type d -exec chmod g+s {} \;
   ```

3. **Existing files keep their ownership**: Recursive ACL application does not
   change file ownership. If files were created with the wrong group (because
   setgid wasn't set), you must fix group ownership separately:
   ```bash
   chgrp -R <groupname> <path>
   ```

4. **Order matters**: Apply setgid and group ownership fixes BEFORE or AFTER
   ACL application, but be aware that the mask will be recalculated based on
   the state at the time of ACL application.

## Sticky Bit for Mutual Protection

In shared workspaces where multiple collaborators have write permission on the
same directory, any collaborator can delete any other collaborator's files
(because deletion requires write permission on the **directory**, not the file).

The **sticky bit** prevents this: when set on a directory, only the file owner,
directory owner, or root can delete or rename files in that directory.

```bash
# Set sticky bit (in addition to setgid)
chmod +t <path>        # adds sticky bit
chmod 3770 <path>      # setgid (2) + sticky (1) + rwxrwx---

# Verify
ls -ld <path>          # look for 'T' or 't' at end of permissions
```

**When to use sticky bit:**
- Shared workspaces where collaborators should not accidentally (or maliciously)
  delete each other's files
- Public directories like `/tmp` (which has mode `1777`)
- Any scenario where write permission on a directory is granted to multiple
  users but mutual protection is required

**Sticky bit vs ACLs:**
- Sticky bit controls **deletion/rename** permissions on files in a directory
- ACLs control **read/write/execute** permissions on the files themselves
- They are complementary: sticky bit protects against deletion, ACLs control access
- Sticky bit does NOT affect the ability to read, modify, or execute files — only
  deletion and renaming

**Interaction with setgid:**
- Setgid (mode `2xxx`): new files/dirs inherit the directory's group ownership
- Sticky bit (mode `?xx1`): only file owner/dir owner/root can delete files
- Both can be combined: `chmod 3770` = setgid + sticky + rwxrwx---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Named user can't access despite ACL entry | Mask too restrictive | Check `mask::` in `getfacl`; adjust `default:mask::` |
| New files don't inherit expected ACLs | No default ACL on parent | Set `default:` entries with `setfacl -d -m` |
| Group members can't access new files | Setgid not set or wrong group | `chmod g+s` and verify `chown :<group>` |
| `chmod +x` leaks execute to others | chmod affects all classes | Use `chmod g+x` instead of `chmod +x` |
| Deep subdirectories lose permissions | Default ACLs not propagating | Verify parent has `default:` entries; subdirs inherit defaults automatically |
| Umask strips expected permissions | Umask applied during creation | Use explicit `chmod` after creation; ACL mask is independent of umask |
| Collaborator deleted another's file | No sticky bit on directory | `chmod +t <dir>` to restrict deletion to file/dir owner and root |
| Recursive ACL has inconsistent masks | `setfacl -R` recalculates per inode | Set mask explicitly after recursive application: `setfacl -R -m m::rwx <path>` |
| Existing files have wrong group | Setgid wasn't set when files were created | `chgrp -R <group> <path>` and `find <path> -type d -exec chmod g+s {} \;` |

## POSIX ACL Evaluation Algorithm

When a process with uid `U` and supplementary groups `G₁...Gₙ` accesses a file
with an ACL, the kernel checks entries in this **strict order** and uses the
**first match**:

1. **`user::` (file owner)** — if `U` equals the file owner → use `user::`
   permissions. **Mask does NOT apply.**

2. **`user:NAME:PERM` (named user)** — if `U` matches a named user entry → use
   that entry's permissions, **AND with mask**.

3. **Group class** — if any of these match:
   - `group::` (U is in the owning group)
   - `group:NAME:PERM` (U is in a named group)
   
   → compute the **union** (most permissive) of all matching group-class
   entries, then **AND with mask**.

4. **`other::`** — none of the above matched → use `other::` permissions.
   **Mask does NOT apply.**

**Critical implications:**
- A user who matches both `user:alice:rwx` and `group::rwx` uses the named
  user entry (step 2), not the group entry.
- A user in multiple groups (e.g., `group:dev:r-x` and `group:ops:rwx`) gets
  the union `rwx` at step 3, then masked.
- The file owner's permissions are **never** affected by the mask.
- The `other::` permissions are **never** affected by the mask.

## Mask Management with setfacl

The `setfacl` command has specific behaviors around mask recalculation:

- **`setfacl -m`**: Auto-recalculates the mask to be the **union** of all
  group-class entries (named users + `group::` + named groups). The mask
  **expands** to cover new or more-permissive entries but does **not shrink**
  when you restrict entries.

- **`setfacl -n -m`**: Suppresses auto-recalculation. Use this when you want
  to add entries without expanding the mask (e.g., adding `user:runner:rwx`
  while keeping `mask::r--` so runner's effective permissions remain `r--`).

- **`setfacl --set`**: Requires you to provide a **complete** ACL specification
  including an explicit `mask::` entry. This is atomic replacement with no
  auto-recalculation — you control every entry.

**Practical guidance:**
- For shared workspaces where you want `mask::rwx`, the default auto-recalculation
  behavior is helpful — it ensures the mask always covers all named entries.
- For variants requiring a **restrictive mask** (e.g., `mask::r--` to limit all
  named entries to read-only), set the mask **after** adding all entries, or use
  `setfacl -n -m` to suppress recalculation when adding entries.
- If you need precise control over the entire ACL, use `setfacl --set` with an
  explicit mask entry.

## Key Invariants

1. **Default ACLs propagate recursively** — subdirectories inherit both access
   and default entries from the parent's defaults.
2. **Mask intersection is automatic** — you cannot prevent it; design your
   default mask and entry permissions to work with it.
3. **Set the default mask to the maximum** permissions any named entry needs
   (typically `rwx`); the creation-mode intersection handles file vs directory
   differentiation.
4. **Named user entries override group entries** — the POSIX check order (see
   above) ensures named user entries take precedence over group-class entries.
5. **Setgid is independent of ACLs** — it controls group ownership inheritance,
   not permission inheritance. Both are needed for a complete shared workspace.
6. **Mask does NOT apply to `user::` or `other::`** — only named users, named
   groups, and the owning group are affected by the mask.
7. **Group-class entries are unioned** — a user matching multiple group entries
   gets the most permissive combination before masking.
8. **Sticky bit protects against deletion, not access** — it prevents non-owners
   from deleting files in a directory, but does not affect read/write/execute
   permissions on the files themselves.
9. **Recursive ACL application recalculates mask per inode** — `setfacl -R -m`
   computes the mask independently for each file/directory based on its
   existing group-class entries. The mask is NOT uniform across the tree
   unless explicitly set afterward.
10. **Default ACLs do NOT propagate group ownership** — only setgid controls
   group inheritance. Both mechanisms are needed for complete shared workspace
   setup, especially when applying to existing trees.
