---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on a Linux shared workspace directory with correct
  ownership, setgid group propagation, per-principal access entries, and
  default (inheritable) ACLs so that newly created files and subdirectories
  automatically receive the intended permission policy.
---

# ACL Permissions & Inheritance

## Execution Protocol

Follow these four phases strictly in order. Do not skip verification.

```
PARSE → PLAN → EXECUTE → VERIFY
```

---

## Phase 1: PARSE — Extract Parameters from the Task

Read the task instruction and fill in this table:

| Parameter | Symbol | How to identify | v01 example |
|-----------|--------|----------------|-------------|
| Workspace path | `$WS` | Directory to configure | `/srv/shared` |
| Owning group | `$GRP` | Group that must own `$WS` | `editors` |
| Base mode | `$MODE` | Requested chmod (often `2xxx` with setgid) | `2770` |
| Full-access users | `FULL[]` | "full read, write, and execute" | `alice`, `bob` |
| Limited users | `LIMITED[]` | Named users with specific allowed/denied actions | `runner` |
| Limited perms | `$LP` | The rwx triple for limited users | `r-x` |
| Denied users | `DENIED[]` | Explicitly blocked named users (may be empty) | _(none)_ |
| Other class | `$OTH` | "outside this access policy" → `---` | `---` |

**Permission triple reference** (directory effective / regular-file effective):

| Intent | Dir entry | File effective | Notes |
|--------|-----------|---------------|-------|
| Full access | `rwx` | `rw-` (x only if `chmod +x`) | Collaborators |
| Read + traverse + run scripts | `r-x` | `r--` / `r-x` if executable | Runner pattern |
| Read-only, no traverse | `r--` | `r--` | Rare |
| Write + traverse, no execute | `rw-` | `rw-` | Rare |
| Explicitly denied | `---` | `---` | Named deny entry |

---

## Phase 2: PLAN — Design the ACL

### Access ACL (on the directory itself)

```
user::rwx                    ← owner (root) always rwx
user:<f1>:rwx                ← each FULL user
user:<f2>:rwx
user:<l1>:$LP                ← each LIMITED user
group::rwx                   ← owning group baseline from $MODE
mask::rwx                    ← auto-calculated; verify after setfacl
other::$OTH                  ← denied class
```

**Named group entries**: If the task grants access to an additional
group (e.g., "marketing should read"), add `g:<group>:r-x` alongside
the user entries. Named groups are also capped by the mask.

### Default ACL (inherited by new children)

Mirror every access entry, plus the owner/group base entries:

```
default:user::rwx            ← new item's owner
default:group::rwx           ← new item's owning group (via setgid)
default:user:<f1>:rwx        ← same as access
default:user:<f2>:rwx
default:user:<l1>:$LP
default:mask::rwx
default:other::$OTH
```

**Why this works for files vs directories**:
- New directories receive the default ACL as both their access ACL and
  their own default ACL → recursive propagation.
- New regular files are created with kernel mode `0666` (no execute bit).
  The file's effective mask = default mask AND `0666` = `rw-`. So:
  - `rwx` entry → effective `rw-` on regular files (no surprise execute).
  - `r-x` entry → effective `r--` on regular files (read only).
  - When a collaborator runs `chmod +x` on a script, the execute bit is
    set, and `r-x` becomes effective `r-x` → runner can execute it.

### Mask management

The mask auto-recalculates as the union of: owning group + all named
users + all named groups. If the most permissive entry is `rwx`, mask
will be `rwx`. Only set it explicitly if the task requires the mask to
restrict named entries (uncommon).

---

## Phase 3: EXECUTE — Run These Commands

**Prerequisite check** (run first, abort if anything fails):

```bash
which setfacl getfacl          # ACL tools installed?
getent group $GRP              # Group exists?
getent passwd $f1 $f2 $l1     # Users exist?
ls -ld $(dirname $WS)          # Parent directory exists?
```

If ACL tools are missing: `apt-get install -y acl`.
If users/groups are missing: create them with `groupadd`/`useradd`.

**Configuration** (one contiguous block — order matters):

```bash
set -euo pipefail

# 1. Create directory, set ownership and base mode FIRST
mkdir -p "$WS"
chown root:"$GRP" "$WS"
chmod "$MODE" "$WS"            # MUST come before setfacl (chmod resets mask)

# 2. Set access ACLs (single atomic call)
setfacl -m u:<f1>:rwx,u:<f2>:rwx,u:<l1>:$LP,o::$OTH "$WS"

# 3. Set default ACLs (single atomic call)
setfacl -d -m u::rwx,g::rwx,u:<f1>:rwx,u:<f2>:rwx,u:<l1>:$LP,o::$OTH "$WS"

# 4. Explicitly confirm mask (safety net)
setfacl -m m::rwx "$WS"
```

**Critical ordering rule**: `chmod` before `setfacl`. Running `chmod`
after `setfacl` can reset the mask, truncating named entries to the new
mask value.

**Do not pre-create any files or subdirectories** inside `$WS` unless
the task explicitly asks. Tests create their own content.

---

## Phase 4: VERIFY — Confirm Every Requirement

Run each check, compare expected vs actual. **Stop and fix** if any
check fails before declaring the task complete.

### 4.1 Directory metadata

```bash
getfacl "$WS"
stat -c '%A %U:%G %a' "$WS"
```

Expected: setgid `s` visible, owner `root`, group `$GRP`, mode matches
`$MODE`, all ACL entries present with correct permissions, mask = `rwx`.

### 4.2 Inheritance — new file

```bash
su -c "touch '$WS/testfile'" $f1
getfacl "$WS/testfile"
```

Expected: inherited ACL entries present, mask = `rw-` (0666 interaction),
group = `$GRP` (setgid propagation).

### 4.3 Inheritance — new subdirectory

```bash
su -c "mkdir '$WS/testdir'" $f1
getfacl "$WS/testdir"
```

Expected: full inherited ACLs **plus** default ACLs for further
propagation, group = `$GRP`, setgid flag present.

### 4.4 Collaborator access

```bash
su -c "echo hello > '$WS/testfile'" $f2    # should succeed (write)
su -c "cat '$WS/testfile'" $f1              # should succeed (read)
su -c "mkdir '$WS/testdir2'" $f2            # should succeed (create)
```

### 4.5 Limited user access

```bash
su -c "cat '$WS/testfile'" $l1     # should succeed (read)
su -c "ls '$WS/'" $l1              # should succeed (traverse)
su -c "touch '$WS/nope'" $l1 2>&1  # should FAIL (no write)
su -c "mkdir '$WS/nodir'" $l1 2>&1 # should FAIL (no write)
su -c "echo x >> '$WS/testfile'" $l1 2>&1  # should FAIL (no write)
```

### 4.6 Denied / outsider access

```bash
# Create a test outsider if no denied user was specified
useradd -M -s /bin/bash __outsider 2>/dev/null || true
su -c "ls '$WS/'" __outsider 2>&1   # should FAIL
su -c "cat '$WS/testfile'" __outsider 2>&1  # should FAIL
userdel __outsider 2>/dev/null || true
```

### 4.7 Clean up all test artifacts

```bash
rm -rf "$WS"/testfile "$WS"/testdir "$WS"/testdir2
```

### 4.8 Final state check

```bash
ls -la "$WS/"        # should be empty except . and ..
getfacl "$WS"        # should match planned ACL exactly
```

---

## Adaptation Decision Rules

When the task differs from v01, apply these transformations:

### R1: Different access policy topology

| If the task says... | Then... |
|---------------------|---------|
| "Group X should have read access" | Add `g:X:r--` to both access and default ACLs |
| "User Y is in group Z but needs extra write" | Add `u:Y:rw-` named entry (overrides group for that user) |
| "Several teams share the workspace" | Add each team as a named group: `g:team1:rwx,g:team2:r-x` |
| "User Y must be explicitly blocked" | Add `u:Y:---` to both access and default ACLs |
| "All authenticated users can read" | Set `other::r--` instead of `other::---` |

### R2: Different permission model

| If the task says... | Then... |
|---------------------|---------|
| "Runner can only read, no execute" | Use `r--` instead of `r-x` for limited user |
| "Collaborators must not execute" | Use `rw-` instead of `rwx` for full users |
| "Mask must limit named entries to rw" | After all setfacl, run `setfacl -m m::rw- "$WS"` |
| "Runner may write to a dropbox subdir" | Create the subdir, set `u:runner:rwx` on it specifically |

### R3: Different inheritance requirements

| If the task says... | Then... |
|---------------------|---------|
| "Files and dirs should have different ACLs" | Not directly possible with defaults alone; set access ACLs on dirs, then use a script/post-creation hook to adjust file ACLs |
| "Deeper than 2 levels" | Default ACLs propagate recursively — no extra work needed |
| "Different creator identities" | Defaults + setgid work regardless of who creates the child |
| "Sticky bit: users can't delete others' files" | Use mode `3770` instead of `2770` (adds sticky bit) |

### R4: Group propagation variants

| If the task says... | Then... |
|---------------------|---------|
| "New files must inherit group G" | Setgid on dir (`chmod g+s` or mode `2xxx`) ensures this |
| "Group G members get access automatically" | Use `g::rwx` or `g:G:rwx` in both access and default ACLs |
| "No setgid, but group still inherited" | Without setgid, new items get creator's primary group — setgid is required |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `setfacl: Operation not supported` | Filesystem lacks ACL support | Mount with `-o acl` or use ext4/xfs (default on Ubuntu) |
| Named entries show `#effective:r--` | Mask is too restrictive | `setfacl -m m::rwx "$WS"` |
| New files have wrong group | Setgid not set | `chmod g+s "$WS"` or recreate with mode `2xxx` |
| `chmod` after `setfacl` broke permissions | chmod resets mask | Re-run `setfacl` after chmod, or always chmod first |
| Runner can still write | Missing `o::---` or runner matched by group entry | Check `getfacl` — if runner is in `$GRP`, add explicit `u:runner:r-x` |
| Outsider can read files | `other` is not `---` | `setfacl -m o::--- "$WS"` and `setfacl -d -m o::--- "$WS"` |
| Nested subdir has wrong ACLs | Default ACLs not set on parent | Re-run `setfacl -d -m ...` on parent directory |
| `su -c` fails with auth prompt | User has no shell or is locked | `usermod -s /bin/bash $USER` |

---

## Quick Reference: Complete Template

```bash
#!/usr/bin/env bash
set -euo pipefail

# === Parameters (edit these for your task) ===
WS="/srv/shared"
GRP="editors"
MODE="2770"
FULL_USERS=("alice" "bob")
LIMITED_USERS=("runner")
LIMITED_PERMS="r-x"
DENIED_USERS=()
OTHER="---"

# === Prerequisites ===
which setfacl getfacl
getent group "$GRP"
for u in "${FULL_USERS[@]}" "${LIMITED_USERS[@]}" "${DENIED_USERS[@]}"; do
  getent passwd "$u"
done

# === Step 1: Create workspace ===
mkdir -p "$WS"
chown root:"$GRP" "$WS"
chmod "$MODE" "$WS"

# === Step 2: Build and apply access ACLs ===
ACL="o::$OTHER"
for u in "${FULL_USERS[@]}"; do ACL+=",u:${u}:rwx"; done
for u in "${LIMITED_USERS[@]}"; do ACL+=",u:${u}:${LIMITED_PERMS}"; done
for u in "${DENIED_USERS[@]}"; do ACL+=",u:${u}:---"; done
setfacl -m "$ACL" "$WS"

# === Step 3: Build and apply default ACLs ===
DEF="u::rwx,g::rwx,o::$OTHER"
for u in "${FULL_USERS[@]}"; do DEF+=",u:${u}:rwx"; done
for u in "${LIMITED_USERS[@]}"; do DEF+=",u:${u}:${LIMITED_PERMS}"; done
for u in "${DENIED_USERS[@]}"; do DEF+=",u:${u}:---"; done
setfacl -d -m "$DEF" "$WS"

# === Step 4: Confirm mask ===
setfacl -m m::rwx "$WS"

# === Step 5: Verify ===
echo "--- Directory ACL ---"
getfacl "$WS"
echo "--- Mode ---"
stat -c '%A %U:%G %a' "$WS"
```

Do **not** create files or subdirectories inside `$WS` unless the task
explicitly requests it. The hidden test suite creates its own content.
