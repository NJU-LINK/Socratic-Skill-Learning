---
name: acl-permissions-inheritance
description: Configure Linux POSIX ACLs for shared workspaces with proper inheritance, group propagation via setgid, and fine-grained access control for multiple principals with different permission levels.
---

# ACL Permissions Inheritance

Configure Linux POSIX Access Control Lists (ACLs) for shared directories where multiple users and groups need different levels of access, with permissions that correctly propagate to newly created files and subdirectories.

## Core Concepts

### POSIX ACL Structure
- **Access ACLs**: Control permissions on the directory/file itself
- **Default ACLs**: Control permissions inherited by newly created children (directories and files)
- **Mask**: Maximum effective permissions for named users, named groups, and the owning group entry (does not affect the owning user `user::` or other `other::`)
- **Setgid bit**: Ensures new files/directories inherit the parent's group ownership

### Permission Model
- **Directories**: r (list contents), w (create/delete entries), x (traverse/access)
- **Files**: r (read contents), w (modify contents), x (execute as program)
- **Effective permissions**: Actual permissions after mask is applied to named entries

## General Procedure

### 1. Analyze Requirements

Identify:
- **Directory path**: Where the shared workspace will be created
- **Owning group**: Which group should own the directory (for setgid propagation)
- **Principals and their access levels**: For each principal, determine:
  - Full collaborators (rwx on directories, rwx on files)
  - Read/traverse users (r-x on directories, r-x on files)
  - Read-only users (r-- on directories, r-- on files)
  - No access (--- for others)
- **Inheritance requirements**: Whether ACLs must propagate to descendants

### 2. Translate Requirements to ACL Entries

**Decision procedure for each principal**:

For each requirement phrase, map to the needed permissions:
- "may traverse directories" → needs `x` on directories
- "may execute scripts/files" → needs `x` on files
- "may read files" → needs `r` on files
- "may create/delete/modify" → needs `w` on directories and files
- "must NOT create/delete/modify" → must NOT have `w`

**Examples**:
- "full read, write, and execute access" → `rwx` for both directories and files
- "traverse directories, execute scripts, read files, but NOT create/delete/modify" → `r-x` (has r and x, but not w)
- "read-only access" → `r--` on files, `r-x` on directories (need x to traverse)

**ACL Precedence Rules** (critical for complex scenarios):
When a user matches multiple ACL entries, Linux evaluates in this order:
1. **Owner (`user::`)** — if the user owns the file
2. **Named user entries (`u:username:`)** — explicit user entries take precedence
3. **Named group entries (`g:groupname:`)** and **owning group (`group::`)** — if user is member of any matching group, the UNION of permissions is used, then masked
4. **Other (`other::`)** — fallback if no other entry matches

**Important**: If a user is in the owning group AND has a named user entry, the named user entry is used (not the group entry). This allows fine-grained overrides.

### 3. Create Directory and Set Base Properties

```bash
# Create the directory
mkdir -p /path/to/shared

# Set ownership (user:group)
chown owner_user:owning_group /path/to/shared

# Set base mode with setgid
# 2770 = setgid + rwx for owner + rwx for group + --- for others
chmod 2770 /path/to/shared
```

**Setgid bit (2000)**: When set on a directory, new files and subdirectories inherit the directory's group ownership rather than the creator's primary group.

### 4. Configure Access ACLs

Set ACLs on the directory itself to control access to the directory and its existing contents:

```bash
# Clear any existing ACLs
setfacl -b /path/to/shared

# Set owner permissions
setfacl -m u::rwx /path/to/shared

# Set owning group permissions
setfacl -m g::rwx /path/to/shared

# Set named user permissions (full collaborators)
setfacl -m u:username:rwx /path/to/shared

# Set named user permissions (read/traverse only)
setfacl -m u:username:r-x /path/to/shared

# Set named group permissions
setfacl -m g:groupname:rwx /path/to/shared

# Set other permissions (typically no access)
setfacl -m o::--- /path/to/shared

# Set mask (controls effective permissions for named entries)
setfacl -m m::rwx /path/to/shared
```

**Alternative: Set all ACLs at once** (cleaner, avoids ordering issues):
```bash
setfacl -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,o::---,m::rwx /path/to/shared
```

**Mask considerations**:
- The mask limits effective permissions for all named users, named groups, AND the owning group (`group::`) entry
- Set mask to the maximum permission needed by any named entry or the owning group
- Example: If alice needs rwx and runner needs r-x, set mask to rwx
- The mask does NOT affect the owning user (`user::`) or other (`other::`). It DOES affect named users, named groups, and the owning group (`group::`) entry

### 5. Configure Default ACLs for Inheritance

Default ACLs determine what ACLs newly created files and subdirectories will inherit:

```bash
# Set default owner permissions
setfacl -d -m u::rwx /path/to/shared

# Set default owning group permissions
setfacl -d -m g::rwx /path/to/shared

# Set default named user permissions (full collaborators)
setfacl -d -m u:username:rwx /path/to/shared

# Set default named user permissions (read/traverse only)
setfacl -d -m u:username:r-x /path/to/shared

# Set default named group permissions
setfacl -d -m g:groupname:rwx /path/to/shared

# Set default other permissions
setfacl -d -m o::--- /path/to/shared

# Set default mask
setfacl -d -m m::rwx /path/to/shared
```

**Alternative: Set all default ACLs at once**:
```bash
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,o::---,m::rwx /path/to/shared
```

**Inheritance behavior**:
- **New directories**: Inherit both access ACLs AND default ACLs (so they continue propagating)
- **New files**: Inherit access ACLs only (no default ACLs), and execute bit is typically not set
- **Setgid propagation**: New items inherit the parent's group ownership

### 6. Apply ACLs Recursively to Existing Trees (if needed)

When you need to apply ACLs to an existing directory tree (not just new items):

```bash
# Apply access ACLs recursively to all existing files and directories
setfacl -R -m u:alice:rwx,u:bob:rwx,u:runner:r-x,o::--- /path/to/shared

# Apply default ACLs recursively (only affects directories, which will then propagate to new children)
setfacl -R -d -m u:alice:rwx,u:bob:rwx,u:runner:r-x,o::--- /path/to/shared
```

**Important notes**:
- `-R` (recursive) applies to all existing items in the tree
- Default ACLs (`-d`) only make sense on directories; applying them recursively will only set them on directories
- For files, you may want different permissions than directories (e.g., no execute bit)
- Use `setfacl -R --set` for a clean slate (replaces all ACLs, not just modifies)

**Example: Different permissions for files vs directories**:
```bash
# Set directory permissions (with execute for traversal)
find /path/to/shared -type d -exec setfacl -m u:alice:rwx,u:runner:r-x {} \;

# Set file permissions (no execute)
find /path/to/shared -type f -exec setfacl -m u:alice:rw-,u:runner:r-- {} \;
```

### 7. Verify Configuration

```bash
# View complete ACL including defaults
getfacl /path/to/shared

# Check directory properties
ls -ld /path/to/shared
stat /path/to/shared

# Test with actual users
su -s /bin/bash username -c "command"
```

### 8. ACL Management Operations

**Remove specific ACL entries** (keep others):
```bash
# Remove a named user entry
setfacl -x u:username /path/to/shared

# Remove a named group entry
setfacl -x g:groupname /path/to/shared

# Remove default ACLs only (keep access ACLs)
setfacl -k /path/to/shared
```

**Replace all ACLs** (clean slate):
```bash
# --set replaces ALL ACLs (access and default) with the specified set
# Warning: This removes any existing entries not in the new set
setfacl --set u::rwx,g::rwx,u:alice:rwx,o::---,m::rwx /path/to/shared

# To set both access and default ACLs at once with --set:
setfacl --set u::rwx,g::rwx,u:alice:rwx,o::---,m::rwx,d:u::rwx,d:g::rwx,d:u:alice:rwx,d:o::---,d:m::rwx /path/to/shared
```

**Copy ACLs from one file to another**:
```bash
# Get ACL from source
getfacl /source/path > /tmp/acl.txt

# Apply to destination
setfacl --set-file=/tmp/acl.txt /destination/path
```

**Important notes**:
- `-x` (remove) only works on named entries, not on `user::`, `group::`, or `other::`
- To change `user::`, `group::`, or `other::`, use `-m` to modify them
- `--set` requires you to specify ALL entries (owner, group, other, mask if ACLs exist)
- `--set` removes default ACLs unless you explicitly include them with `d:` prefix

## Common Patterns

### Pattern 1: Full Collaboration + Read-Only Access

**Scenario**: Multiple collaborators need full access, some users need read-only access, others have no access.

```bash
# Setup
mkdir -p /srv/workspace
chown root:workgroup /srv/workspace
chmod 2770 /srv/workspace

# Access ACLs
setfacl -m u::rwx,u:collab1:rwx,u:collab2:rwx,u:reader:r-x,g:workgroup:rwx,o::---,m::rwx /srv/workspace

# Default ACLs (inheritance)
setfacl -d -m u::rwx,u:collab1:rwx,u:collab2:rwx,u:reader:r-x,g:workgroup:rwx,o::---,m::rwx /srv/workspace
```

**Result**:
- collab1, collab2: Full read/write/execute
- reader: Can read and traverse, cannot modify
- Others: No access

### Pattern 2: Group-Based Access with Individual Overrides

**Scenario**: A group has baseline access, but specific individuals need different permissions.

```bash
# Setup
mkdir -p /srv/project
chown root:devteam /srv/project
chmod 2770 /srv/project

# Access ACLs
setfacl -m u::rwx,g:devteam:rwx,u:manager:rwx,u:contractor:r--,o::---,m::rwx /srv/project

# Default ACLs
setfacl -d -m u::rwx,g:devteam:rwx,u:manager:rwx,u:contractor:r--,o::---,m::rwx /srv/project
```

**Result**:
- devteam members: Full access (via group)
- manager: Full access (explicit)
- contractor: Read-only (explicit override)

### Pattern 3: Multi-Level Access Hierarchy

**Scenario**: Different levels of access (admin, editor, viewer).

```bash
# Setup
mkdir -p /srv/content
chown root:content /srv/content
chmod 2770 /srv/content

# Access ACLs
setfacl -m u::rwx,u:admin:rwx,u:editor:rwx,u:viewer:r-x,o::---,m::rwx /srv/content

# Default ACLs
setfacl -d -m u::rwx,u:admin:rwx,u:editor:rwx,u:viewer:r-x,o::---,m::rwx /srv/content
```

## Critical Considerations

### 1. Mask and Effective Permissions

The mask controls the maximum effective permissions for named users, named groups, AND the owning group entry:

```bash
# Example: mask limits effective permissions
setfacl -m u:alice:rwx /path  # Requested: rwx
setfacl -m m::r-x /path       # Mask: r-x
# Effective for alice: r-x (not rwx)

# The mask ALSO limits the owning group entry:
setfacl -m g::rwx /path       # Requested: rwx
# With mask::r-x, effective for group:: is r-x (not rwx)
```

**Rule**: Set the mask to the maximum permission level needed by any named entry or the owning group.

**Using the mask to restrict**: You can deliberately set the mask lower than the maximum requested permissions to restrict all named entries and the owning group simultaneously. For example, setting `mask::r-x` makes all named users and the owning group effectively read+execute, regardless of their requested permissions. This is useful for temporarily revoking write access without changing individual entries.

### 2. File vs Directory Permissions

When default ACLs are inherited:
- **Directories**: Inherit all permissions including execute (for traversal)
- **Files**: Inherit permissions but execute bit is typically not set by default
- **Umask**: When default ACLs are set on the parent directory, the umask is **ignored**; the default ACL alone determines inherited permissions. The umask applies only when no default ACL exists.

**Implication**: A default ACL of `rwx` for a user means:
- On directories: rwx (full access)
- On files: rw- (read/write, no execute unless explicitly set)

### 3. Setgid and Group Propagation

The setgid bit ensures:
- New files/directories inherit the parent's group ownership
- Combined with ACLs, this provides consistent group-based access

**Without setgid**: New items would have the creator's primary group, breaking group-based ACL access.

### 4. Default ACL Propagation

Default ACLs only propagate to **newly created** items:
- Existing items are NOT affected
- New directories inherit default ACLs (continuing the chain)
- New files inherit access ACLs only (no default ACLs)

**Implication**: If you need to change inheritance rules, you must:
1. Update default ACLs on the parent
2. Optionally update existing items with `setfacl -R -m` (recursive)

### 5. Testing Inheritance

Always test with actual file/directory creation:

```bash
# Create test items as different users
su -s /bin/bash user1 -c "touch /path/test1.txt"
su -s /bin/bash user2 -c "mkdir /path/testdir"

# Check inherited ACLs
getfacl /path/test1.txt
getfacl /path/testdir

# Verify access controls work
su -s /bin/bash user3 -c "cat /path/test1.txt"  # Should work or fail as expected
```

### Pattern 4: Sticky Bit for Shared Write Directories

**Scenario**: Multiple collaborators have write access to a shared directory. Without the sticky bit, any collaborator can delete any other collaborator's files (because directory write permission allows unlinking entries).

```bash
# Setup with sticky bit (mode 3770 instead of 2770)
mkdir -p /srv/dropbox
chown root:workgroup /srv/dropbox
chmod 3770 /srv/dropbox  # setgid + sticky + rwx for owner and group

# ACLs as normal
setfacl -m u::rwx,u:alice:rwx,u:bob:rwx,g:workgroup:rwx,o::---,m::rwx /srv/dropbox
setfacl -d -m u::rwx,u:alice:rwx,u:bob:rwx,g:workgroup:rwx,o::---,m::rwx /srv/dropbox
```

**Result**:
- alice and bob can both create files
- alice CANNOT delete bob's files (sticky bit prevents this)
- bob CANNOT delete alice's files
- Only the file owner or root can delete/rename a file

**When to use**: Any shared workspace where multiple users have write access and you want to prevent accidental or malicious deletion of each other's files. This is the same principle as `/tmp` (mode 1777).

### Pattern 5: Mask-Based Restriction (Temporary Write Revocation)

**Scenario**: You want to temporarily revoke write access for all collaborators without changing individual ACL entries. The mask provides a "global throttle" for named entries and the owning group.

```bash
# Initial setup: full collaboration
mkdir -p /srv/project
chown root:devteam /srv/project
chmod 2770 /srv/project
setfacl -m u::rwx,u:alice:rwx,u:bob:rwx,g:devteam:rwx,o::---,m::rwx /srv/project
setfacl -d -m u::rwx,u:alice:rwx,u:bob:rwx,g:devteam:rwx,o::---,m::rwx /srv/project

# Verify current effective permissions
getfacl /srv/project
# user:alice:rwx  (effective rwx)
# user:bob:rwx    (effective rwx)
# group::rwx      (effective rwx)

# TEMPORARILY revoke write: set mask to r-x
setfacl -m m::r-x /srv/project
setfacl -d -m m::r-x /srv/project  # Also update default for new items

# Check effective permissions
getfacl /srv/project
# user:alice:rwx  #effective:r-x  (write revoked)
# user:bob:rwx    #effective:r-x  (write revoked)
# group::rwx      #effective:r-x  (write revoked)
# mask::r-x

# Restore write access: set mask back to rwx
setfacl -m m::rwx /srv/project
setfacl -d -m m::rwx /srv/project
```

**Key insight**: The mask acts as an upper bound on effective permissions for ALL named users, named groups, and the owning group. By lowering the mask, you can restrict everyone simultaneously without modifying individual entries. This is useful for:
- Temporary lockdowns (e.g., during maintenance)
- Read-only periods (e.g., code freeze)
- Emergency response (revoke write access quickly)

**Important**: The mask does NOT affect `user::` (owner) or `other::`. Only named entries and `group::` are limited.

### Pattern 6: Deep Inheritance Verification

**Scenario**: You need to verify that ACLs propagate correctly through multiple generations of subdirectories, not just one level.

```bash
# Setup
mkdir -p /srv/shared
chown root:editors /srv/shared
chmod 2770 /srv/shared
setfacl -m u::rwx,u:alice:rwx,u:runner:r-x,g::rwx,o::---,m::rwx /srv/shared
setfacl -d -m u::rwx,u:alice:rwx,u:runner:r-x,g::rwx,o::---,m::rwx /srv/shared

# Create multi-level test structure as a collaborator
su -s /bin/bash alice -c "mkdir -p /srv/shared/level1/level2/level3"
su -s /bin/bash alice -c "touch /srv/shared/level1/level2/level3/deepfile.txt"

# Verify ACLs at each depth
echo "Level 1:"
getfacl /srv/shared/level1 | grep -E "^(user|group|mask|other|default):"

echo "Level 2:"
getfacl /srv/shared/level1/level2 | grep -E "^(user|group|mask|other|default):"

echo "Level 3:"
getfacl /srv/shared/level1/level2/level3 | grep -E "^(user|group|mask|other|default):"

# Verify group ownership at each depth
ls -ld /srv/shared/level1 /srv/shared/level1/level2 /srv/shared/level1/level2/level3
# All should show group=editors and setgid bit (s)

# Test access controls at depth
su -s /bin/bash runner -c "cat /srv/shared/level1/level2/level3/deepfile.txt"  # Should succeed
su -s /bin/bash runner -c "echo test >> /srv/shared/level1/level2/level3/deepfile.txt"  # Should fail

# Clean up
rm -rf /srv/shared/level1
```

**What to verify**:
1. Each directory has the same access ACLs as the parent
2. Each directory has the same default ACLs as the parent (so propagation continues)
3. Group ownership is `editors` at all depths (setgid working)
4. Access controls work correctly at all depths
5. New files created at depth inherit correct ACLs

**Common failure modes**:
- Default ACLs not set on parent → children don't inherit
- Setgid not set → group ownership doesn't propagate
- Mask too restrictive → effective permissions are limited unexpectedly

## Troubleshooting

### Problem: Named user cannot access despite ACL entry

**Check**:
1. Is the mask limiting effective permissions? `getfacl` shows effective permissions
2. Does the user have execute permission on parent directories (path traversal)?
3. Are there conflicting group memberships?

### Problem: New files don't inherit expected permissions

**Check**:
1. Are default ACLs set on the parent directory?
2. Is the parent directory's setgid bit set (for group inheritance)?
3. Are you checking a newly created file, not an existing one?

### Problem: User can modify files but shouldn't

**Check**:
1. Is the user a member of the owning group with write permission?
2. Is the mask allowing write permission?
3. Are there group ACL entries granting write?

### Problem: User in owning group gets unexpected permissions

**Scenario**: User is a member of the owning group AND has a named user entry with different permissions.

**Explanation**: POSIX ACL precedence rules mean the named user entry is used, NOT the group entry. If you set `group::r-x` but `u:alice:rwx`, alice gets rwx (named entry wins).

**Check**:
```bash
# See all entries and check for conflicts
getfacl /path/to/file

# If user has named entry, that's what's used (not group)
# To restrict alice, you must change the named entry, not the group
setfacl -m u:alice:r-x /path/to/file
```

**Important**: If you want group-based control, don't create named user entries for group members. Use only the `group::` entry and rely on group membership.

## Verification Checklist

- [ ] Directory has correct ownership (user:group)
- [ ] Setgid bit is set (mode 2xxx)
- [ ] Access ACLs grant correct permissions to all principals
- [ ] Default ACLs match access ACLs for inheritance
- [ ] Mask allows maximum needed permissions
- [ ] Other class has appropriate access (usually none)
- [ ] New files inherit correct ACLs
- [ ] New directories inherit correct ACLs AND default ACLs
- [ ] Setgid propagates group ownership to new items
- [ ] Access controls work as expected when tested with actual users
