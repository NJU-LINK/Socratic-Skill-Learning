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

**Two rules:**

1. **Never use backslash-newline line continuations in shell commands.**
   LLM-driven shell execution frequently mangles `\` + newline sequences.
   Always use single-line comma-separated format for `setfacl`:
   ```bash
   # CORRECT:
   setfacl -d -m u::rwx,g::rwx,o::---,u:alice:rwx /path
   ```

2. **Do NOT create any test files or directories inside the workspace.**
   The hidden tests create their own content. Leave the workspace empty.
   Verify the configuration by inspecting the directory ACL only
   (`getfacl`, `ls -ld`, `stat`). If you must test inheritance, clean up
   immediately before finishing.

## Step-by-Step Procedure

### Step 1: Extract Policy from the Task

Read the task description carefully. Every ACL task has these elements
(values will differ across variants — extract them from YOUR task):

| Element | Question to answer | Look for |
|---|---|---|
| Workspace path | Where to create the directory? | e.g., `/srv/shared`, `/workspace/team` |
| Owning group | Which group owns it? | e.g., `editors`, `devteam`, `staff` |
| Base mode | What chmod including setgid? | e.g., `2770`, `2750`, `2700` |
| Full-access principals | Who needs `rwx`? | Named users or groups with "full access" |
| Restricted principals | Who has limited access? | Users with specific allow/deny rules |
| Denied principals | Who gets nothing? | "everyone else", "others", specific users |

**IMPORTANT**: Do not assume values from a previous task. Always re-extract
from the current task description.

### Step 2: Verify Prerequisites

```bash
which setfacl getfacl
```

Check that all referenced users and groups exist:
```bash
id <user1>; id <user2>; getent group <group>
```

### Step 3: Create the Workspace Directory

Clean any prior state, then create:

```bash
rm -rf <WORKSPACE_PATH>
mkdir -p <WORKSPACE_PATH>
chown root:<OWNING_GROUP> <WORKSPACE_PATH>
chmod <BASE_MODE> <WORKSPACE_PATH>
```

- `2` prefix = setgid bit → new items inherit the owning group
- Owner is `root` unless the task specifies otherwise

### Step 4: Set Access ACLs on the Directory

All named entries in **one single-line command**:

```bash
setfacl -m u:<user1>:<perms>,u:<user2>:<perms>,g:<grp>:<perms> <WORKSPACE_PATH>
```

**Permission mapping** — translate the task's natural language to ACL bits:

| Task says | ACL bits |
|---|---|
| "full access" / "read, write, execute" | `rwx` |
| "read and traverse" / "read-only with directory access" | `r-x` |
| "traverse only" / "can enter directories" | `--x` |
| "read files" / "read only" | `r--` |
| "execute scripts" | `--x` |
| "no access" / "denied" | `---` |

For named groups, use `g:<group>:<perms>` instead of `u:<user>:<perms>`.

### Step 5: Set Default ACLs for Inheritance

**This is the critical step.** Default ACLs on a directory become the access
ACLs of newly created children. Use single-line format:

```bash
setfacl -d -m u::rwx,g::rwx,o::---,u:<user1>:<perms>,u:<user2>:<perms> <WORKSPACE_PATH>
```

Required base entries:
- `d:u::rwx` — owner of new items gets full access
- `d:g::rwx` — owning group gets full access (adjust if task requires less)
- `d:o::---` — others get no access (adjust if task allows some)

Then add the same named-user/named-group entries as in Step 4, with the
same permissions.

The default mask auto-calculates as the union of all named-user, named-group,
and owning-group entries, so full-access users are not clipped.

### Step 6: Verify Configuration Only

Check the directory state — **do not create files inside the workspace**:

```bash
getfacl <WORKSPACE_PATH>
ls -ld <WORKSPACE_PATH>
stat -c "%a %U %G" <WORKSPACE_PATH>
```

Confirm:
- `flags: -s-` or `s` in group-execute position (setgid active)
- All named-user and named-group entries present in both access and default ACL
- `mask::rwx` (not clipped)
- `other::---` (or whatever the denied policy requires)
- Directory is empty (`ls -A <WORKSPACE_PATH>` shows nothing)

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

## Worked Example

This example uses specific names to show the command structure. **Always
substitute the actual values from your task — do not copy these literally.**

```bash
# 1. Create workspace (adapt path, group, mode to YOUR task)
rm -rf /srv/shared
mkdir -p /srv/shared
chown root:editors /srv/shared
chmod 2770 /srv/shared

# 2. Access ACLs (adapt users and permissions to YOUR task)
setfacl -m u:alice:rwx,u:bob:rwx,u:runner:r-x /srv/shared

# 3. Default ACLs for inheritance (adapt to YOUR task)
setfacl -d -m u::rwx,g::rwx,o::---,u:alice:rwx,u:bob:rwx,u:runner:r-x /srv/shared

# 4. Verify only — no test files created
getfacl /srv/shared
ls -ld /srv/shared
```

## Adapting to Different Task Variants

Common variations you may encounter and how to handle them:

**Different group ownership**: Change `chown root:<group>` and `g::` entries.

**Multiple restricted users**: Add each as a separate `u:<name>:<perms>` entry.
Example: `u:viewer:r--,u:auditor:r-x` gives different restricted levels.

**Group-based access**: Use `g:<group>:<perms>` entries instead of `u:` entries.
Users who are members of that group inherit permissions through group membership.

**Mixed user+group access**: Some collaborators get access via group membership
(no explicit ACL entry needed) while others need explicit named-user entries.
Only add `u:<user>:rwx` for users whose access must come through ACL, not group.

**Different base modes**: `2750` gives group r-x (not rwx), `2700` gives only
owner access. Adjust `g::` in default ACL to match.

**Multiple workspaces**: Repeat Steps 3-6 for each path.

The invariant pattern: **create → setgid → access ACL → default ACL → verify**.

## Common Pitfalls

1. **Backslash-newline in commands**: Always fails in LLM shell execution.
   Use single-line comma-separated format (see "Execution Safety").

2. **Creating test files inside the workspace**: The hidden tests create their
   own content. Do not create, then clean up test files — just skip creating
   them entirely. Verify with `getfacl` only.

3. **Forgetting default ACLs**: Access ACLs only apply to the directory itself.
   Without default ACLs, new files/dirs won't inherit any named-user entries.

4. **Forgetting the mask**: The ACL mask clips effective permissions. If the
   mask is too restrictive (e.g., `rw-` on the directory), even `rwx` named
   entries get clipped. The mask auto-recalculates on `setfacl -m` unless
   `-n` (no-mask) is passed.

5. **Setgid not propagating**: Setgid must be set on every subdirectory. With
   setgid and default ACLs on the parent, new subdirectories automatically
   inherit both. Without setgid, new items get the creator's primary group.

6. **Confusing ACL mask with group permission**: When ACLs are active, `ls -l`
   shows the ACL mask in the group permission field, not the owning group's
   actual permissions. Use `getfacl` for the real picture.

7. **Not setting `d:o::---`**: If the default other entry isn't explicitly set,
   it may inherit a permissive value from system defaults.

8. **Not cleaning stale state**: If the workspace directory already exists from
   a prior run, `rm -rf` it first. Stale ACLs or ownership will cause failures.

9. **Copying example values instead of extracting from task**: The worked
   example uses specific names (`alice`, `bob`, `runner`, `editors`, `/srv/shared`)
   for illustration. Always extract the actual values from your task description.
