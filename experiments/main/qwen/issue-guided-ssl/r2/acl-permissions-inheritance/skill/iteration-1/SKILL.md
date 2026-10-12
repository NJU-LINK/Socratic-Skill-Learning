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
# Collaborators: full access
setfacl -m u:<collab1>:rwx <workspace_path>
setfacl -m u:<collab2>:rwx <workspace_path>

# Restricted users: partial access
setfacl -m u:<restricted1>:r-x <workspace_path>

# Others: no access (already set by base mode, but explicit for clarity)
setfacl -m o::--- <workspace_path>
```

### Step 4: Set Default ACLs for Inheritance

```bash
# Owner of new items: full access
setfacl -m d:u::rwx <workspace_path>

# Owning group of new items: full access
setfacl -m d:g::rwx <workspace_path>

# Collaborators on new items: full access
setfacl -m d:u:<collab1>:rwx <workspace_path>
setfacl -m d:u:<collab2>:rwx <workspace_path>

# Restricted users on new items: partial access
setfacl -m d:u:<restricted1>:r-x <workspace_path>

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
- Principals with access from both group membership and explicit ACL entries
- Additional denied principals beyond the generic `other` class

**Adaptation**: Adjust the `setfacl` commands in Steps 3-4 to include all required principals with appropriate permissions.

### Variation: permission_model

Parameterize the permission sets:
- Different read/write/execute combinations per principal
- Cases where directory traversal and file execution requirements differ
- Policies that rely on the ACL mask to preserve or restrict named entry permissions

**Adaptation**: 
- Adjust permission strings in `setfacl` commands (e.g., `r-x`, `rw-`, `r--`)
- Set mask explicitly if you need to restrict effective permissions below the union of named entries
- For different directory vs file permissions, use separate default ACL entries

### Variation: inheritance_and_group_propagation

Parameterize the inheritance depth and group propagation:
- Deeper directory trees (handled automatically by default ACL cascading)
- Multiple generations of subdirectories (automatic)
- Different creator identities and creation orders (handled by setgid + default ACLs)

**Adaptation**: 
- The default ACL mechanism handles arbitrary depth automatically
- Setgid ensures group ownership propagation regardless of creator
- No special configuration needed for depth; the mechanism is invariant

## Common Pitfalls

1. **Forgetting default ACLs**: Access ACLs only affect the directory itself, not children. Always set both access and default ACLs.

2. **Mask too restrictive**: If mask is set below the union of named entries, effective permissions are capped. Set `d:m::rwx` unless you intentionally want to restrict.

3. **Not using setgid**: Without setgid, new items get the creator's primary group, breaking group-based access policies.

4. **Confusing file creation mode with ACL permissions**: Files created with mode `0666` will have mask `rw-` regardless of default ACL. This is correct behavior; use `chmod g+x` to enable execute for specific files.

5. **Testing only as root**: Always test as actual users to verify permission enforcement. Root bypasses ACL checks.

6. **Removing the workspace itself**: The workspace directory with its ACL configuration is the infrastructure artifact that tests verify against. After testing, clean up ONLY the test content you created inside the workspace, NEVER the workspace directory itself. The workspace must exist with all ACLs in place when evaluation runs.

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
