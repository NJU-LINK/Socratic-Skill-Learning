---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on Linux shared workspaces with correct ownership,
  setgid group propagation, per-principal access policies, and default ACL
  inheritance for newly created files and subdirectories.
---

# ACL Permissions & Inheritance Configuration

## Overview

Configure a shared workspace directory with POSIX ACLs so that multiple
principals (users and groups) receive precisely the access the policy requires,
and that access propagates correctly to all future descendants.

## Execution Safety — Read First

**Never use backslash-newline line continuations in shell commands.**
LLM-driven shell execution frequently mangles `\` + newline sequences,
splitting what should be one argument into separate tokens and causing
`setfacl` to interpret commas as filenames.

**Always use single-line comma-separated format:**

```bash
# WRONG — fragile, will break in task_shell:
setfacl -d -m \
  u::rwx,\
  g::rwx,\
  o::---,\
  u:alice:rwx \
  /srv/shared

# CORRECT — always works:
setfacl -d -m u::rwx,g::rwx,o::---,u:alice:rwx /srv/shared
```

If a command is long, that is fine. Send it as one line.

## Step-by-Step Procedure

### Step 1: Parse the Policy

Extract these elements from the task description:

| Element | What to identify | Example |
|---|---|---|
| Workspace path | Directory to create/configure | `/srv/shared` |
| Owning group | Group that owns the workspace | `editors` |
| Base mode | chmod value including setgid | `2770` |
| Full-access collaborators | Named users/groups needing `rwx` | `alice`, `bob` |
| Restricted principals | Named users/groups with partial access | `runner` → `r-x` |
| Denied principals | Everyone else → `other::---` | — |
| Inheritance scope | Files, subdirs, or both | Both |

### Step 2: Verify Prerequisites

```bash
which setfacl getfacl
id alice; id bob; id runner; getent group editors
```

### Step 3: Create the Workspace Directory

If the directory might already exist, remove and recreate it cleanly:

```bash
rm -rf <WORKSPACE_PATH>
mkdir -p <WORKSPACE_PATH>
chown root:<OWNING_GROUP> <WORKSPACE_PATH>
chmod <BASE_MODE> <WORKSPACE_PATH>
```

- `2` prefix = setgid bit → new items inherit the owning group
- Owner is typically `root` (or as specified)
- Base mode `770` = owner and group have full access, others have none

### Step 4: Set Access ACLs on the Directory

All named-user and named-group entries in **one single-line command**:

```bash
setfacl -m u:<user1>:rwx,u:<user2>:rwx,u:<restricted>:r-x <WORKSPACE_PATH>
```

**Permission mapping for restricted principals:**

| Requirement | ACL bits |
|---|---|
| Traverse directories only | `--x` |
| Read + traverse | `r-x` |
| Read files | `r--` |
| Execute scripts (when chmod +x) | `--x` |
| Create/modify/delete files | `-w-` |
| Full access | `rwx` |

For named groups, use `g:<group>:<perms>` instead of `u:<user>:<perms>`.

### Step 5: Set Default ACLs for Inheritance

**This is the critical step.** Default ACLs on a directory become the access
ACLs of newly created children. Use single-line format:

```bash
setfacl -d -m u::rwx,g::rwx,o::---,u:<full_user1>:rwx,u:<full_user2>:rwx,u:<restricted>:r-x <WORKSPACE_PATH>
```

Entry-by-entry:
- `d:u::rwx` — owner of new items gets full access
- `d:g::rwx` — owning group gets full access
- `d:o::---` — others get no access
- `d:u:<user>:rwx` or `d:u:<user>:r-x` — named user entries propagate

The default mask auto-calculates as the union of all named-user, named-group,
and owning-group entries (typically `rwx`), so full-access users are not clipped.

### Step 6: Verify

Run `getfacl` to confirm the complete state, then behaviorally test.

```bash
getfacl <WORKSPACE_PATH>
ls -ld <WORKSPACE_PATH>
stat -c "%a %U %G" <WORKSPACE_PATH>
```

**Do NOT pre-create test files if the task says tests will create their own.**
Only verify the directory-level configuration is correct.

## How Inheritance Works at Runtime

**New subdirectory**: Inherits the full default ACL as both its access ACL and
its own default ACL. The setgid bit also propagates. All permission bits
(including execute for traversal) are preserved at `rwx` effective.

**New regular file**: Inherits the default ACL as its access ACL, but the
creation mode from `open()`/`creat()` (typically `0666`) acts as an additional
mask. The effective mask becomes `rw-`:
- Full-access users → `rw-` effective (execute only after explicit `chmod +x`)
- Restricted users with `r-x` default → `r--` effective (read only)
- When a collaborator runs `chmod +x`, the mask expands to `rwx` and execute
  becomes effective for all entries that include it

This is correct behavior — scripts are executable only after being explicitly
marked so by the creator.

## Concrete Template (Adapt Placeholders)

For the common pattern of "two full-access collaborators + one read-only user":

```bash
# 1. Create workspace
rm -rf /srv/shared
mkdir -p /srv/shared
chown root:editors /srv/shared
chmod 2770 /srv/shared

# 2. Access ACLs (single line)
setfacl -m u:alice:rwx,u:bob:rwx,u:runner:r-x /srv/shared

# 3. Default ACLs for inheritance (single line)
setfacl -d -m u::rwx,g::rwx,o::---,u:alice:rwx,u:bob:rwx,u:runner:r-x /srv/shared

# 4. Verify
getfacl /srv/shared
ls -ld /srv/shared
```

Adapt user names, group names, permission bits, and paths to match the actual
task. The structure (create → access ACL → default ACL → verify) is invariant.

## Common Pitfalls

1. **Backslash-newline in commands**: Always fails in LLM shell execution.
   Use single-line comma-separated format (see "Execution Safety").

2. **Forgetting default ACLs**: Access ACLs only apply to the directory itself.
   Without default ACLs, new files/dirs won't inherit any named-user entries.

3. **Forgetting the mask**: The ACL mask clips effective permissions. If the
   mask is too restrictive (e.g., `rw-` on the directory), even `rwx` named
   entries get clipped. The mask auto-recalculates on `setfacl -m` unless
   `-n` (no-mask) is passed.

4. **Setgid not propagating**: Setgid must be set on every subdirectory. With
   setgid and default ACLs on the parent, new subdirectories automatically
   inherit both. Without setgid, new items get the creator's primary group.

5. **Confusing ACL mask with group permission**: When ACLs are active, `ls -l`
   shows the ACL mask in the group permission field, not the owning group's
   actual permissions. Use `getfacl` for the real picture.

6. **Not setting `d:o::---`**: If the default other entry isn't explicitly set,
   it may inherit a permissive value from system defaults.

7. **Pre-creating test files when told not to**: Some tasks explicitly say
   "do not pre-create test files." The tests will create their own content.

8. **Not cleaning stale state**: If the workspace directory already exists from
   a prior run, `rm -rf` it first. Stale ACLs or ownership from a previous
   attempt will cause test failures.

## Generalization

The approach works for any combination of:

- **Multiple named users** with different permission levels
- **Named groups** as ACL entries (`g:<group>:<perms>`)
- **Mixed access** — some users via group membership, others via explicit ACL
- **Deeper directory trees** — default ACLs propagate recursively to any depth
- **Different base modes** — adjust chmod to match the policy
- **Multiple workspaces** — repeat the procedure for each path
- **Collaborators creating files for others** — setgid + default ACLs ensure
  group ownership and ACL inheritance regardless of which user creates the item

The invariant pattern: **create → setgid → access ACL → default ACL → verify**.
