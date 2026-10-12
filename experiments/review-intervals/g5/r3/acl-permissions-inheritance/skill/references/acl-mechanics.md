# POSIX ACL Mechanics Reference

## 1. Access ACLs vs Default ACLs

Every file and directory on an ACL-enabled filesystem can have an **access ACL**. Directories can additionally have a **default ACL**.

### Access ACLs
- Control who can access the file/directory itself
- Checked on every access attempt (read, write, execute, traverse)
- Present on all files and directories

### Default ACLs (directories only)
- Define the access ACL that **newly created children** will inherit
- When a new file or directory is created inside a parent with default ACLs:
  1. The child's access ACL = `default_ACL_entries AND requested_mode`
  2. If the child is a **directory**, it also copies the parent's default ACLs as its own defaults (cascading inheritance)
- Files do NOT get default ACLs (they cannot have children)

### The requested_mode
The mode requested by the creating system call:
- `open()` for regular files: typically `0666` (rw-rw-rw- before umask)
- `mkdir()`: typically `0777` (rwxrwxrwx before umask)
- Scripts created with explicit execute: `0777`

**Important**: With default ACLs, the umask is **ignored**. The default ACL takes its place.

## 2. ACL Entry Types

An ACL consists of these entries:

| Entry | Meaning | Affected by mask? |
|-------|---------|-------------------|
| `user::` | File owner permissions | No |
| `user:<name>:` | Named user permissions | **Yes** |
| `group::` | Owning group permissions | **Yes** |
| `group:<name>:` | Named group permissions | **Yes** |
| `mask::` | Maximum effective permissions for named entries | N/A (is the mask) |
| `other::` | Everyone else | No |

## 3. The Mask and Effective Permissions

The **mask** entry is the maximum permission set for:
- All named user entries (`user:<name>:`)
- All named group entries (`group:<name>:`)
- The owning group entry (`group::`)

**Effective permissions** = entry permissions AND mask

Example:
```
user:alice:rwx     # requested
mask::rw-          # mask
user:alice:rwx     #effective:rw-   ← actual permissions alice gets
```

Only `user::` (owner) and `other::` are NOT affected by the mask.

### Why the mask matters
- If you set `mask::rw-`, no named user or group can have execute permission, even if their entry says `rwx`
- If you set `mask::rwx`, named entries get exactly what their entry specifies
- The mask is displayed as the "group" field in `ls -l` output when ACLs are present (shown by the `+` suffix)

## 4. chmod Interaction with ACLs

**Critical rule**: When a file/directory has ACLs, `chmod` modifies the **mask** entry, not the traditional group permission bits.

```
# Before chmod
user:alice:rwx
mask::rwx           ← chmod will change THIS
group::rwx          ← traditional group bits (unchanged by chmod with ACLs)

# After: chmod 640 file
mask::r--           ← mask changed to r--
user:alice:rwx      #effective:r--   ← alice now only gets read!
```

**Best practice**: Always run `chmod` to set the base mode **before** setting ACLs. Never run `chmod` on a file/directory after ACLs are configured unless you intentionally want to change the mask.

## 5. Inheritance Mechanics

### How default ACLs propagate

When a process creates a new item inside a directory with default ACLs:

```
Parent default ACL:
  user::rwx
  user:alice:rwx
  user:runner:r-x
  group::rwx
  mask::rwx
  other::---
```

**New file** (created with mode 0666):
```
Child access ACL = default AND 0666:
  user::rw-          (rwx AND rw-)
  user:alice:rw-     (rwx AND rw-)  #effective:rw-
  user:runner:r--    (r-x AND rw-)  #effective:r--
  group::rw-         (rwx AND rw-)  #effective:rw-
  mask::rw-          (rwx AND rw-)
  other::---         (--- AND rw-)
```

**New directory** (created with mode 0777):
```
Child access ACL = default AND 0777:
  user::rwx          (rwx AND rwx)
  user:alice:rwx     (rwx AND rwx)  #effective:rwx
  user:runner:r-x    (r-x AND rwx)  #effective:r-x
  group::rwx         (rwx AND rwx)  #effective:rwx
  mask::rwx          (rwx AND rwx)
  other::---         (--- AND rwx)

Child default ACL = parent's default ACL (exact copy):
  default:user::rwx
  default:user:alice:rwx
  default:user:runner:r-x
  default:group::rwx
  default:mask::rwx
  default:other::---
```

### The r-x pattern for "read + conditional execute"

A default ACL entry of `user:runner:r-x` produces different effective permissions depending on what's created:

| Created item | Mode | r-x AND mode | Effective |
|-------------|------|-------------|-----------|
| Regular file | 0666 | r-x AND rw- = r-- | Read only |
| Executable script | 0777 | r-x AND rwx = r-x | Read + execute |
| Directory | 0777 | r-x AND rwx = r-x | Traverse |

This is why `r-x` is the universal pattern for "read files, execute scripts, traverse directories, but don't write."

## 6. Setgid and Group Propagation

The **setgid** bit (mode 2000, shown as `s` in group execute position) on a directory causes:
- All newly created files and subdirectories inherit the directory's group ownership
- Without setgid: new items get the creator's primary group
- With setgid: new items get the directory's group, regardless of creator's primary group

This is essential for shared workspaces because:
1. It ensures consistent group ownership across all items
2. Collaborators who are members of the group can access items created by others
3. Combined with `group::rwx` in the ACL, it provides a backup access path

## 7. Directory-Level Operations: Create, Delete, Rename

A critical POSIX concept: **creating, deleting, or renaming a file requires write permission on the parent directory**, not on the file itself.

This means:
- A user with `r-x` on a directory can read and traverse it, but **cannot create, delete, or rename** any files within it
- A user with `rwx` on a directory can create, delete, and rename files within it, regardless of the files' own permissions
- Even if a file has `rwx` for everyone, a user without write on the containing directory cannot delete it

**Example**: In the v01 task, `runner` has `r-x` on `/srv/shared`:
- Can list directory contents (read)
- Can traverse into subdirectories (execute)
- **Cannot** create new files (requires write on directory)
- **Cannot** delete existing files (requires write on directory)
- **Cannot** rename files (requires write on directory)

This is why the `r-x` permission pattern is sufficient to restrict `runner` from modifying the workspace, even though `runner` can read files and traverse directories.

## 8. The Sticky Bit

The **sticky bit** (mode 1000, shown as `t` in other execute position) on a directory modifies delete behavior:
- Without sticky bit: any user with write permission on the directory can delete any file within it
- With sticky bit: only the file's owner, the directory's owner, or root can delete a file

Common use case: `/tmp` has mode `1777` (rwxrwxrwt) — everyone can create files, but only the owner can delete their own files.

For shared workspaces where collaborators need write access but shouldn't delete each other's files:
```bash
chmod 3770 /shared/workspace  # setgid + sticky bit
```

This combines:
- `2000` (setgid): new files inherit the directory's group
- `1000` (sticky): only file owners can delete their files
- `770`: owner and group have full access

## 9. ACL Evaluation Order

When a process accesses a file, the kernel checks permissions in this order:

1. If process UID == file owner → use `user::` entry
2. If process UID matches a named user entry → use that entry (AND mask)
3. If process GID or supplementary groups match `group::` → use `group::` (AND mask)
4. If process GID or supplementary groups match a named group entry → use that entry (AND mask)
5. Otherwise → use `other::` entry

**Important**: If a user matches BOTH a named user entry AND a group entry, the named user entry is used (step 2 wins over step 4). This means explicit `user:alice:rwx` takes precedence over any group-based permissions alice might have.

## 10. Common Pitfalls

1. **Running chmod after setfacl**: Changes the mask, potentially breaking named entries
2. **Forgetting the mask**: If mask is too restrictive, named entries get reduced effective permissions
3. **Not setting default ACLs**: Children won't inherit the desired permissions
4. **Not using setgid**: New items get the creator's primary group instead of the workspace group
5. **Confusing access and default ACLs**: Access ACLs control the directory itself; default ACLs control children
6. **Assuming umask applies**: With default ACLs, umask is ignored; the default ACL replaces it
7. **Assuming file permissions control deletion**: Deletion requires write on the parent directory, not the file itself

## 11. Useful Commands

```bash
# View ACLs
getfacl <path>

# Set access ACL entries
setfacl -m u:<user>:<perms>,g:<group>:<perms> <path>

# Set default ACL entries
setfacl -d -m u:<user>:<perms> <path>

# Remove all ACLs
setfacl -b <path>

# Remove specific entry
setfacl -x u:<user> <path>

# Set mask
setfacl -m m::<perms> <path>

# Recursive ACL set (existing files only)
setfacl -R -m u:<user>:<perms> <path>

# Recursive with default (for directories)
setfacl -R -m u:<user>:<perms> <path>
find <path> -type d -exec setfacl -d -m u:<user>:<perms> {} \;
```
