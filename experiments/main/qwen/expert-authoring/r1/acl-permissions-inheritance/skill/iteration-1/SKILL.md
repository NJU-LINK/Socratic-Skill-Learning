---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on a Linux shared workspace directory with correct
  ownership, setgid group propagation, per-principal access entries, and
  default (inheritable) ACLs so that newly created files and subdirectories
  automatically receive the intended permission policy.
---

# ACL Permissions & Inheritance Configuration

## 1. Read the Task Specification Carefully

Extract these four elements from the task YAML:

| Element | What to look for | Example (v01) |
|---------|-----------------|---------------|
| **Workspace path** | Directory to create / configure | `/srv/shared` |
| **Owning group** | Group that must own the directory | `editors` |
| **Collaborators** | Named users / groups with full or specific access | `alice`, `bob` (full rwx) |
| **Restricted users** | Named users with limited permissions | `runner` (read + traverse + execute, no write) |
| **Denied class** | Everyone else | `other::---` |
| **Base mode** | Requested chmod on the workspace (often with setgid) | `2770` |

## 2. Verify Prerequisites

```bash
# ACL tools must be present
which setfacl getfacl
# Relevant users and groups must exist
getent group <GROUP_NAME>
getent passwd <USER1> <USER2> ...
# Workspace parent directory must exist
ls -la $(dirname <WORKSPACE_PATH>)
```

If ACL tools are missing: `apt-get install -y acl`.

## 3. Create the Workspace Directory

```bash
mkdir -p <WORKSPACE_PATH>
chown root:<GROUP_NAME> <WORKSPACE_PATH>
chmod <BASE_MODE> <WORKSPACE_PATH>
```

**Setgid (`2xxx`)**: ensures every new file and subdirectory inherits the
owning group instead of the creator's primary group. This is critical for
group-based access propagation.

## 4. Design the Access ACL

### 4.1 Classify Each Principal

For every user or group mentioned in the task, decide the **access ACL
entry** on the workspace directory itself:

| Role | Typical access ACL | Rationale |
|------|--------------------|-----------|
| Full collaborator | `u:<name>:rwx` | Read, write, execute (traverse) |
| Read-only / runner | `u:<name>:r-x` | Traverse + read + conditional execute; no write prevents create/delete/modify |
| Write-no-execute | `u:<name>:rw-` | Can edit files but not traverse directories (rare) |
| Denied named user | `u:<name>:---` | Explicitly block a specific user |
| Owning group | `g::rwx` (or as required) | Baseline for group members |
| Others | `o::---` | Block everyone not covered above |

### 4.2 Understand the Mask

The **mask** entry (`m::`) caps the *effective* permissions of:
- All named user entries (`u:<name>:...`)
- All named group entries (`g:<name>:...`)
- The owning group entry (`g::...`)

The mask is **auto-recalculated** by `setfacl` as the union of all the
above entries whenever you modify an ACL. You can also set it explicitly:

```bash
setfacl -m m::rwx <PATH>
```

Set the mask to the **most permissive** entry among collaborators so
their effective permissions are not truncated.

### 4.3 Apply Access ACLs

Use a single `setfacl -m` call to set all entries atomically:

```bash
setfacl -m u:<collab1>:rwx,u:<collab2>:rwx,u:<restricted>:r-x,o::--- <WORKSPACE_PATH>
```

## 5. Design the Default (Inheritance) ACL

Default ACLs on a directory define the **access ACL** that newly created
children receive. They also propagate as default ACLs on new
subdirectories, so the policy carries forward recursively.

### 5.1 Key Rules

1. **Every access entry needs a matching default entry** if the policy
   must hold for descendants.
2. **Files vs directories**: When a file is created with `open()` or
   `touch`, the kernel requests mode `0666` (no execute). The resulting
   **file mask** is the intersection of the default mask and `0666`,
   yielding `rw-`. This means:
   - `r-x` on a restricted user → effective `r--` on regular files (read only)
   - `r-x` on a restricted user → effective `r-x` on executables created with `chmod +x` (read + execute)
   - `rwx` on a collaborator → effective `rw-` on regular files (read + write, no execute unless explicitly set)
3. **Directories** created inside the workspace receive the full default
   ACL as both their access ACL *and* their own default ACL, so the
   policy recurses automatically.

### 5.2 Apply Default ACLs

```bash
setfacl -d -m u::rwx,g::rwx,u:<collab1>:rwx,u:<collab2>:rwx,u:<restricted>:r-x,o::--- <WORKSPACE_PATH>
```

- `u::rwx` — the *owner* of new items gets full access.
- `g::rwx` — the *owning group* (inherited via setgid) gets full access.
- Named user entries mirror the access ACL.
- `o::---` — outsiders remain blocked.
- The mask is auto-calculated to `rwx` (union of all named + group entries).

## 6. Verification Checklist

After configuration, run through these checks:

```bash
# 6.1 Inspect the full ACL
getfacl <WORKSPACE_PATH>

# 6.2 Verify directory properties
stat -c '%A %U:%G' <WORKSPACE_PATH>
# Should show setgid (the 's' in group execute position) and correct owner:group

# 6.3 Test inheritance by creating a file
su -c "touch <WORKSPACE_PATH>/testfile" <collab_user>
getfacl <WORKSPACE_PATH>/testfile
# Should show inherited ACL entries; mask typically rw- (from 0666 creation mode)

# 6.4 Test inheritance by creating a subdirectory
su -c "mkdir <WORKSPACE_PATH>/testdir" <collab_user>
getfacl <WORKSPACE_PATH>/testdir
# Should show full inherited ACLs AND default ACLs for further propagation

# 6.5 Test restricted user permissions
su -c "cat <WORKSPACE_PATH>/testfile" <restricted_user>   # should succeed (read)
su -c "ls <WORKSPACE_PATH>/" <restricted_user>            # should succeed (traverse)
su -c "touch <WORKSPACE_PATH>/nope" <restricted_user>     # should fail (no write)
su -c "mkdir <WORKSPACE_PATH>/nodir" <restricted_user>    # should fail (no write)

# 6.6 Test denied users
su -c "ls <WORKSPACE_PATH>/" <outsider_user>              # should fail (other::---)

# 6.7 Clean up test artifacts
rm -rf <WORKSPACE_PATH>/testfile <WORKSPACE_PATH>/testdir
```

## 7. Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Forgetting setgid | New files get creator's group, not workspace group | `chmod g+s <DIR>` or use mode `2xxx` |
| Mask too restrictive | Named users get `#effective:r--` instead of `rwx` | Explicitly `setfacl -m m::rwx` |
| Missing default ACL entries | Children don't inherit policy for specific users | Add `-d -m` for every access entry |
| Default ACL without `u::` or `g::` | Owner/group of new files get unexpected permissions | Always include `u::rwx` and `g::rwx` (or appropriate) in defaults |
| Setting ACLs before chmod | chmod can reset the mask, truncating named entries | Set base mode first, then ACLs |
| Pre-creating test content | Task may say "do not create files" — tests create their own | Read the task; only create the directory itself |

## 8. Adapting to Variation

The task family varies along three axes. Use this decision table:

### Access Policy Topology
- **Multiple collaborators with same access**: add each as `u:<name>:rwx`.
- **Mixed group + named user access**: a user may inherit some rights from
  group membership and have additional rights from a named ACL entry;
  the named entry takes precedence for that user.
- **Several denied principals**: add `u:<name>:---` for each, or rely on
  `o::---` if they have no other path to access.

### Permission Model
- **Different rwx combinations**: map each role to its exact `{r,w,x}`
  triple for both directories and (via creation-mode masking) files.
- **Mask-based restriction**: if the task requires the mask to limit
  named entries (e.g., collaborators get `rwx` in their entry but mask
  is `rw-`), set the mask explicitly after all entries.
- **Execute-only on scripts**: `r-x` default ACL gives `r--` on regular
  files (via 0666 mask) and `r-x` on executables — matches "read files,
  execute scripts" naturally.

### Inheritance & Group Propagation
- **Deeper trees**: default ACLs propagate recursively; no extra work
  needed beyond the top-level defaults.
- **Multiple generations**: verify by creating nested content and
  checking ACLs at each level.
- **Different creator identities**: as long as default ACLs are set and
  setgid is active, the policy holds regardless of who creates the child.

## 9. Complete Worked Template

```bash
#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/srv/shared"
GROUP="editors"
COLLABS=("alice" "bob")
RESTRICTED=("runner")

# Step 1: Create workspace
mkdir -p "$WORKSPACE"
chown root:"$GROUP" "$WORKSPACE"
chmod 2770 "$WORKSPACE"

# Step 2: Build access ACL entries
ACL_ENTRIES=""
for u in "${COLLABS[@]}"; do
  ACL_ENTRIES+="u:${u}:rwx,"
done
for u in "${RESTRICTED[@]}"; do
  ACL_ENTRIES+="u:${u}:r-x,"
done
ACL_ENTRIES+="o::---"

setfacl -m "$ACL_ENTRIES" "$WORKSPACE"

# Step 3: Build default ACL entries
DEF_ENTRIES="u::rwx,g::rwx,"
for u in "${COLLABS[@]}"; do
  DEF_ENTRIES+="u:${u}:rwx,"
done
for u in "${RESTRICTED[@]}"; do
  DEF_ENTRIES+="u:${u}:r-x,"
done
DEF_ENTRIES+="o::---"

setfacl -d -m "$DEF_ENTRIES" "$WORKSPACE"

# Step 4: Verify
getfacl "$WORKSPACE"
```

Adapt the arrays and permission triples to match the specific task
requirements. Do **not** pre-create files or directories inside the
workspace unless the task explicitly asks for it.
