---
name: acl-permissions-inheritance
description: Configure POSIX ACLs on shared directories with proper inheritance, mask management, and multi-principal access policies
---

# POSIX ACL Configuration for Shared Workspaces

This skill configures Linux POSIX ACLs on shared directories to support multi-principal access policies with correct inheritance to newly created files and subdirectories.

## Core Concepts

### Access ACLs vs Default ACLs

- **Access ACLs** (`setfacl -m u:name:perms`): Control access to the directory itself
- **Default ACLs** (`setfacl -m d:u:name:perms`): Template that new children inherit

A directory can have both. Regular files have only access ACLs (files cannot have children).

### Inheritance Mechanism

When a new item is created inside a directory with default ACLs:

- **New subdirectory**: Inherits parent's default ACL as both its access ACL AND its default ACL (cascades to arbitrary depth)
- **New file**: Inherits parent's default ACL as its access ACL only

This automatic inheritance satisfies multi-generational permission propagation without per-file configuration.

### The Mask Mechanism (Critical)

Every ACL has a **mask** entry that caps effective permissions for:
- All named user entries (`user:alice:rwx`)
- All named group entries (`group:devs:r-x`)
- The owning group entry (`group::rwx`)

**Effective permission = entry AND mask**

The owner entry (`user::rwx`) and other entry (`other::---`) are NOT affected by the mask.

When adding entries with `setfacl`, the mask auto-recalculates as the union of all named-user, named-group, and owning-group entries. You can set it explicitly with `setfacl -m m::perms`.

### File Creation Mode Interaction

When a process creates a file, it specifies a mode (typically `0666` for regular files, `0777` for executables/directories). With ACLs present:

- **File created with mode 0666** (touch, echo, text editors):
  - Named user entries keep their letters
  - **Mask is intersected with creation mode's group bits** (`rw-` from `0666`)
  - Example: Default ACL `u:alice:rwx` → file gets `u:alice:rwx` but effective `rw-` (mask is `rw-`)
  - Runner's `u:runner:r-x` → effective `r--` (read only, no execute) ✓ Correct for ordinary files

- **chmod g+x on an ACL'd file**:
  - Modifies the GROUP_OBJ entry AND the mask, adding execute
  - Mask becomes `rwx`
  - Runner's `u:runner:r-x` → effective `r-x` ✓ Runner can execute the script

**Key insight**: You do NOT need to give restricted users write permission on the directory for file execution to work. The execute bit on files is controlled by the file's own ACL, not the directory's.

### Setgid for Group Propagation

Setgid bit (`chmod g+s` or mode `2xxx`) ensures new items inherit the parent directory's group ownership regardless of creator's primary group. This works alongside ACL inheritance to maintain consistent group-based access.

### POSIX ACL Evaluation Order (Critical for Mixed Access)

When a process accesses a file, POSIX ACLs are evaluated in this specific order:

1. **Owner check**: If process UID == file owner → use `user::` entry (NOT affected by mask)
2. **Named user check**: If process UID matches a `user:name:` entry → use that entry (masked)
3. **Group check**: If process is member of owning group OR matches any `group:name:` entry → use the **most permissive matching group entry** (each masked individually, then unioned)
4. **Other**: Use `other::` entry (NOT affected by mask)

**Key implications:**
- Named user entries take precedence over group entries. If alice has `u:alice:rwx` and is also in `editors` group with `g:editors:r-x`, alice gets `rwx` (from named user entry), not the union.
- For group-based access, all matching group entries are checked and the most permissive is used.
- This matters for variants where "principals whose access comes partly from group membership and partly with explicit ACL entries."

**Example**: If you want a user to have different permissions on files they own vs files others own:
- As owner: `user::rwx` applies (full access to own files)
- As non-owner: `user:alice:rwx` applies (named user entry, masked)

### Named Group ACL Entries

In addition to named user entries, you can add named group entries:

```bash
# Grant group 'devs' read-execute access
setfacl -m g:devs:r-x <workspace_path>

# Default entry for inheritance
setfacl -m d:g:devs:r-x <workspace_path>
```

Named group entries are useful when:
- Multiple users should share the same permissions (add them to a group, grant group access)
- You want to separate "collaborator individuals" from "collaborator teams"
- The spec requires "different mixes of named users and groups"

**Important**: Named group entries are subject to the mask, just like named user entries. The mask must accommodate the union of all named entries (users + groups + owning group).

### Idempotent Reconfiguration

If the workspace directory already exists with incorrect ACLs, you have two options:

**Option 1: Clear and reconfigure** (recommended for clean slate)
```bash
# Remove all ACLs (keeps base permissions)
setfacl -b <workspace_path>

# Then reconfigure from scratch (Steps 2-4)
```

**Option 2: Replace all ACLs at once** (atomic)
```bash
# Use --set to replace entire ACL (not -m which merges)
setfacl --set u::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,g::rwx,m::rwx,o::--- <workspace_path>
setfacl -d --set u::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,g::rwx,m::rwx,o::--- <workspace_path>
```

**Why this matters**: Variants may require reconfiguring an existing workspace. Using `-m` (merge) can leave stale entries. Using `-b` (remove) or `--set` (replace) ensures a clean configuration.

### Recursive ACL Application

When applying ACLs to an existing directory tree (not just a fresh workspace), use the `-R` flag:

```bash
# Apply ACLs recursively to all existing files and directories
setfacl -R -m u:alice:rwx <workspace_path>

# Set default ACLs recursively (only affects directories)
setfacl -R -m d:u:alice:rwx <workspace_path>
```

**Important**: 
- `-R` applies to all existing content but does NOT set default ACLs on files (files can't have defaults)
- Default ACLs set with `-R -m d:...` only take effect on directories
- After recursive application, new content created in any directory will inherit from that directory's default ACLs

**Use case**: Variants where "the workspace already exists with content" or "apply ACLs to an existing project directory."

### Sticky Bit for Shared Workspaces

The sticky bit (`+t`, mode `1xxx` or `3xxx` with setgid) prevents users from deleting files they don't own, even if they have write permission on the directory:

```bash
# Set both setgid and sticky bit
chmod 3770 <workspace_path>  # setgid (2000) + sticky (1000) + rwxrwx---
```

**Behavior**:
- Collaborators can create files in the workspace
- Collaborators can modify/delete their OWN files
- Collaborators CANNOT delete files owned by other collaborators
- Root can still delete any file

**Use case**: Variants requiring "several actors must share a workspace without exposing it to unrelated accounts" or preventing accidental deletion of collaborators' work.

**Interaction with ACLs**: Sticky bit works independently of ACLs. The sticky bit controls deletion/renaming, while ACLs control read/write/execute access.

## Generalized Configuration Procedure

### Step 1: Define Access Policy

Identify three principal classes:
1. **Collaborators**: Named users/groups with full access (typically `rwx`)
2. **Restricted users**: Named users with partial access (e.g., `r-x` for read/traverse/execute)
3. **Others**: Everyone else (typically `---`)

### Step 2: Create Workspace Directory

```bash
mkdir -p <workspace_path>
chown <owner>:<group> <workspace_path>
chmod 2770 <workspace_path>  # setgid + rwx for owner/group, no access for others
```

### Step 3: Set Access ACLs on the Directory

```bash
# Optional: Clear existing ACLs for clean reconfiguration
# setfacl -b <workspace_path>

# Collaborators (named users): full access
setfacl -m u:<collab1>:rwx <workspace_path>
setfacl -m u:<collab2>:rwx <workspace_path>

# Collaborators (named groups): full access
# setfacl -m g:<collab_group1>:rwx <workspace_path>

# Restricted users: partial access
setfacl -m u:<restricted1>:r-x <workspace_path>

# Explicitly denied principals (beyond 'other')
# setfacl -m u:<denied_user>:--- <workspace_path>

# Others: no access (already set by base mode, but explicit for clarity)
setfacl -m o::--- <workspace_path>

# Access mask: explicitly set to union of all named entries
# (auto-calculated by setfacl, but explicit is safer)
# setfacl -m m::rwx <workspace_path>
```

### Step 4: Set Default ACLs for Inheritance

```bash
# Owner of new items: full access
setfacl -m d:u::rwx <workspace_path>

# Owning group of new items: full access
setfacl -m d:g::rwx <workspace_path>

# Collaborators (named users) on new items: full access
setfacl -m d:u:<collab1>:rwx <workspace_path>
setfacl -m d:u:<collab2>:rwx <workspace_path>

# Collaborators (named groups) on new items: full access
# setfacl -m d:g:<collab_group1>:rwx <workspace_path>

# Restricted users on new items: partial access
setfacl -m d:u:<restricted1>:r-x <workspace_path>

# Explicitly denied principals on new items
# setfacl -m d:u:<denied_user>:--- <workspace_path>

# Others on new items: no access
setfacl -m d:o::--- <workspace_path>

# Mask: set to union of all named entries to avoid restricting effective permissions
setfacl -m d:m::rwx <workspace_path>
```

### Step 5: Verify Configuration

```bash
getfacl <workspace_path>
```

Check:
- Access ACL entries match policy
- Default ACL entries exist and match
- Mask is set appropriately (typically `rwx` to not restrict named entries)
- Setgid flag is present (`flags: -s-`)

### Step 6: Test Inheritance

Create test files and directories as a collaborator:

```bash
su - <collaborator> -c "touch <workspace_path>/testfile"
su - <collaborator> -c "mkdir <workspace_path>/testdir"
su - <collaborator> -c "echo '#!/bin/bash' > <workspace_path>/script.sh && chmod +x <workspace_path>/script.sh"

getfacl <workspace_path>/testfile
getfacl <workspace_path>/testdir
getfacl <workspace_path>/script.sh
```

Verify:
- Files: mask is `rw-`, restricted users have effective `r--` (read only)
- Directories: inherit both access and default ACLs, mask is `rwx`
- Executable scripts: mask is `rwx`, restricted users have effective `r-x` (can execute)

### Step 7: Test Permission Enforcement

```bash
# Restricted user should be able to read/traverse
su - <restricted> -c "cat <workspace_path>/testfile"  # should succeed
su - <restricted> -c "ls <workspace_path>/testdir"    # should succeed

# Restricted user should NOT be able to write/create
su - <restricted> -c "echo 'test' >> <workspace_path>/testfile"  # should fail
su - <restricted> -c "touch <workspace_path>/newfile"             # should fail
su - <restricted> -c "mkdir <workspace_path>/newdir"              # should fail

# Restricted user should be able to execute scripts
su - <restricted> -c "<workspace_path>/script.sh"  # should succeed

# Outsiders should have no access
su - <outsider> -c "cat <workspace_path>/testfile"  # should fail
su - <outsider> -c "ls <workspace_path>/"           # should fail
```

### Step 8: Clean Up Test Content (Preserve Workspace)

**Critical**: The workspace directory itself is the deliverable. Only remove test content you created during verification.

```bash
# Remove ONLY test files/directories you created
rm -rf <workspace_path>/testfile
rm -rf <workspace_path>/testdir
rm -rf <workspace_path>/script.sh

# NEVER do this:
# rm -rf <workspace_path>  # WRONG - this removes the deliverable!
```

### Step 9: Final Verification (Workspace Must Persist)

Verify the workspace exists with correct ACLs and is empty:

```bash
# Check workspace exists
ls -ld <workspace_path>

# Check it's empty (only . and ..)
ls -la <workspace_path>

# Verify ACLs are still in place
getfacl <workspace_path>

# Verify setgid and ownership
stat -c "%A %U %G" <workspace_path>
```

Expected final state:
- Workspace directory exists
- Directory is empty (no test files)
- All ACLs are configured correctly
- Setgid bit is set
- Ownership is correct

## Handling Family Variations

### Variation: access_policy_topology

Parameterize the principal lists:
- Different numbers of collaborators and restricted users
- Principals with access from both group membership and partly from explicit ACL entries
- Additional denied principals beyond the generic `other` class
- Collaboration patterns where several actors must share a workspace without exposing it to unrelated accounts

**Adaptation**: 
- Adjust the `setfacl` commands in Steps 3-4 to include all required principals with appropriate permissions
- Use named group entries (`g:groupname:perms`) when multiple users should share permissions
- Use explicit deny entries (`u:denied_user:---`) for principals that must be blocked beyond `other`
- Remember ACL evaluation order: named user entries take precedence over group entries

**Example**: If the task requires "group `devs` has read access, user `alice` has full access, user `eve` is explicitly denied":
```bash
setfacl -m g:devs:r-x /workspace      # group entry
setfacl -m u:alice:rwx /workspace     # named user (takes precedence for alice)
setfacl -m u:eve:--- /workspace       # explicit deny for eve
setfacl -m d:g:devs:r-x /workspace    # inherit group entry
setfacl -m d:u:alice:rwx /workspace   # inherit named user
setfacl -m d:u:eve:--- /workspace     # inherit deny
```

### Variation: permission_model

Parameterize the permission sets:
- Different read/write/execute combinations per principal
- Cases where directory traversal and file execution requirements differ
- Policies that rely on the ACL mask to preserve or restrict named entry permissions
- Tasks where the effective access pattern is more subtle than simply granting everyone full control

**Adaptation**: 
- Adjust permission strings in `setfacl` commands (e.g., `r-x`, `rw-`, `r--`)
- Set mask explicitly if you need to restrict effective permissions below the union of named entries
- For different directory vs file permissions, use separate default ACL entries
- Use the mask as an active restriction mechanism: set `d:m::r-x` to cap all named entries at `r-x` effective

**Default Mask as Active Restriction**:
The default mask controls the maximum effective permissions for ALL named entries on inherited children:
- `d:m::rwx` → named entries keep their full permissions (intersected with creation mode)
- `d:m::r-x` → all named entries capped at `r-x` effective on new files, `r-x` on new directories
- `d:m::r--` → all named entries capped at `r--` effective (read-only)

The default mask is intersected with the creation mode:
- Files created with mode `0666`: effective mask = default_mask AND `rw-`
- Directories created with mode `0777`: effective mask = default_mask AND `rwx`

**Example**: If you want collaborators to have `rwx` on the workspace but only `r-x` on all inherited content:
```bash
# Access ACL: collaborators get full access to workspace itself
setfacl -m u:alice:rwx /workspace
setfacl -m m::rwx /workspace

# Default ACL: cap inherited content at r-x
setfacl -m d:u:alice:rwx /workspace  # entry says rwx
setfacl -m d:m::r-x /workspace       # but mask caps at r-x
# New files: effective r-- (r-x AND rw- from 0666)
# New dirs: effective r-x (r-x AND rwx from 0777)
```

**Example**: If you want all collaborators to have `rwx` on directories but only `rw-` on files:
```bash
# Default ACL for directories: rwx (mask rwx)
setfacl -m d:u:alice:rwx /workspace
setfacl -m d:m::rwx /workspace
# Files created with mode 0666 will automatically get mask rw-, giving effective rw-
# Directories created with mode 0777 will get mask rwx, giving effective rwx
```

### Variation: inheritance_and_group_propagation

Parameterize the inheritance depth and group propagation:
- Deeper directory trees (handled automatically by default ACL cascading)
- Multiple generations of subdirectories (automatic)
- Inherited access that must remain correct for newly created files versus new subdirectories
- Setups where group propagation and inherited ACLs must continue to work under different creator identities and creation orders

**Adaptation**: 
- The default ACL mechanism handles arbitrary depth automatically
- Setgid ensures group ownership propagation regardless of creator
- No special configuration needed for depth; the mechanism is invariant
- Test with multiple creators (alice, bob) to ensure permissions work regardless of who creates content

## Common Pitfalls

1. **Forgetting default ACLs**: Access ACLs only affect the directory itself, not children. Always set both access and default ACLs.

2. **Mask too restrictive**: If mask is set below the union of named entries, effective permissions are capped. Set `d:m::rwx` unless you intentionally want to restrict.

3. **Not using setgid**: Without setgid, new items get the creator's primary group, breaking group-based access policies.

4. **Confusing file creation mode with ACL permissions**: Files created with mode `0666` will have mask `rw-` regardless of default ACL. This is correct behavior; use `chmod g+x` to enable execute for specific files.

5. **Testing only as root**: Always test as actual users to verify permission enforcement. Root bypasses ACL checks.

6. **Removing the workspace itself**: The workspace directory with its ACL configuration is the infrastructure artifact that tests verify against. After testing, clean up ONLY the test content you created inside the workspace, NEVER the workspace directory itself. The workspace must exist with all ACLs in place when evaluation runs.

7. **Ignoring ACL evaluation order**: Named user entries take precedence over group entries. If a user has both `u:alice:rwx` and is in a group with `g:editors:r-x`, alice gets `rwx` (from named user), not the union. This matters for variants with mixed group/user access.

8. **Forgetting group default ACLs**: If you add a named group entry (`g:devs:r-x`) to the access ACL but forget the default (`d:g:devs:r-x`), new children won't inherit the group permission.

9. **Using -m (merge) for reconfiguration**: If a directory already has stale ACL entries, using `-m` only adds/updates. Use `setfacl -b` to clear first, or `setfacl --set` to replace atomically.

10. **Confusing owning group entry with named group entry**: `group::rwx` is the owning group (set by `chgrp`). `group:editors:rwx` is a named group entry. They are separate entries in the ACL, both subject to the mask.

11. **Forgetting recursive application for existing content**: If the workspace already has files/directories, `-m` only affects the target directory, not its contents. Use `setfacl -R -m ...` to apply to existing content. Default ACLs set with `-R` only take effect on directories (files can't have defaults).

12. **Not considering sticky bit for collaborative workspaces**: In shared workspaces where multiple collaborators create files, the sticky bit (`chmod +t` or mode `1xxx`/`3xxx`) prevents users from deleting files they don't own. Without it, any user with write permission on the directory can delete any file in it.

13. **Confusing access mask with default mask**: The access mask (`m::`) controls effective permissions on the directory itself. The default mask (`d:m::`) controls the mask on inherited children. They are independent entries. Changing one does not affect the other.

## Reference: Complete v01 Example

For the seed task (collaborators alice/bob with rwx, runner with r-x, others denied):

```bash
# Create workspace
mkdir -p /srv/shared
chown root:editors /srv/shared
chmod 2770 /srv/shared

# Access ACLs
setfacl -m u:alice:rwx /srv/shared
setfacl -m u:bob:rwx /srv/shared
setfacl -m u:runner:r-x /srv/shared

# Default ACLs
setfacl -m d:u::rwx /srv/shared
setfacl -m d:g::rwx /srv/shared
setfacl -m d:u:alice:rwx /srv/shared
setfacl -m d:u:bob:rwx /srv/shared
setfacl -m d:u:runner:r-x /srv/shared
setfacl -m d:o::--- /srv/shared
setfacl -m d:m::rwx /srv/shared
```

This configuration ensures:
- Alice and bob have full access to workspace and all descendants
- Runner can traverse directories, read files, and execute scripts, but cannot create/modify/delete
- Others have no access
- Permissions inherit correctly to arbitrary depth
- Setgid maintains `editors` group ownership
