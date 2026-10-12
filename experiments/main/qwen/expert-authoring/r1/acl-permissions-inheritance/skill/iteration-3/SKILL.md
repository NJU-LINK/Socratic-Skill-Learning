---
name: acl-permissions-inheritance
description: >
  Configure POSIX ACLs on a Linux shared workspace directory with correct
  ownership, setgid group propagation, per-principal access entries, and
  default (inheritable) ACLs so that newly created files and subdirectories
  automatically receive the intended permission policy.
---

# ACL Permissions & Inheritance

## Protocol: PARSE → EXECUTE → VERIFY → STOP

### Phase 1: PARSE — Extract from Task

| Parameter | Symbol | v01 example |
|-----------|--------|-------------|
| Workspace path | `$WS` | `/srv/shared` |
| Owning group | `$GRP` | `editors` |
| Base mode (setgid `2xxx`) | `$MODE` | `2770` |
| Full-access users | `FULL[]` | `alice`, `bob` → `rwx` |
| Limited users + perms | `LIMITED[]`, `$LP` | `runner` → `r-x` |
| Denied users | `DENIED[]` | _(empty)_ |
| Other class | `$OTH` | `---` |

**Permission intent → rwx triple** (directory / file effective):

| Intent | Dir | File effective |
|--------|-----|---------------|
| Full access | `rwx` | `rw-` (x only if chmod +x) |
| Read + traverse + run scripts | `r-x` | `r--` on regular; `r-x` on executables |
| Read-only | `r--` | `r--` |
| Denied | `---` | `---` |

### Phase 2: EXECUTE — Single Command Block

**Order matters**: chmod before setfacl (chmod resets the mask).
**Do not** create any files or subdirectories inside `$WS` — tests create their own.

```bash
set -euo pipefail

# Prerequisites
which setfacl getfacl
getent group "$GRP"    # must exist; create with groupadd if missing
for u in "${FULL[@]}" "${LIMITED[@]}" "${DENIED[@]}"; do getent passwd "$u"; done

# Create workspace
mkdir -p "$WS"
chown root:"$GRP" "$WS"
chmod "$MODE" "$WS"

# Access ACLs
setfacl -m u:alice:rwx,u:bob:rwx,u:runner:r-x,o::--- "$WS"

# Default ACLs (mirror access entries + u::/g:: base)
setfacl -d -m u::rwx,g::rwx,u:alice:rwx,u:bob:rwx,u:runner:r-x,o::--- "$WS"

# Confirm mask
setfacl -m m::rwx "$WS"
```

Replace the explicit user names with loop-built strings for variants with
many principals (see Template section below).

**Why this works for files vs directories**:
- New directories receive the default ACL as both access and default → recursive.
- Files created with kernel mode `0666` → effective mask `rw-`. So `rwx`→`rw-`,
  `r-x`→`r--` on regular files. When a collaborator runs `chmod +x`, the
  execute bit is set and `r-x` becomes effective `r-x` → limited user can run it.

### Phase 3: VERIFY — Lightweight Sanity Check

```bash
getfacl "$WS"
stat -c '%A %U:%G %a' "$WS"
```

Confirm: setgid `s` flag, owner `root`, group `$GRP`, mode `$MODE`,
all named entries present, mask = `rwx`, default entries present.

**Then stop.** Do not create test files, do not search for test scripts,
do not create outsider users. The hidden test suite handles verification.

### Phase 4: STOP

The task is complete once `$WS` exists with correct ACLs and empty contents.
Do **not**:
- Pre-create any files or subdirectories inside `$WS`
- Search `/app` for test files (they are injected at test time)
- Create extra test users
- Run additional verification commands

---

## ACL Design Reference

### Access ACL anatomy

```
user::rwx              ← owner (root) always rwx
u:<name>:rwx           ← each full collaborator
u:<name>:$LP           ← each limited user
g::rwx                 ← owning group (from $MODE)
mask::rwx              ← auto-calculated; verify after setfacl
other::$OTH            ← denied class
```

Named groups (if task grants group-based access): `g:<group>:perms` —
also capped by mask.

### Default ACL anatomy

Mirror every access entry plus base entries:
```
default:u::rwx, default:g::rwx
default:u:<f1>:rwx, default:u:<l1>:$LP
default:o::$OTH
```

### Mask management

Mask = union of (owning group + named users + named groups).
Auto-recalculated by setfacl. Only set explicitly if the task requires
the mask to restrict entries (uncommon — see adaptation rules).

### Critical ordering

`chmod` before `setfacl`. Running chmod after setfacl resets the mask,
truncating named entries. If you must chmod later, re-run setfacl after.

---

## Complete Parameterized Template

```bash
#!/usr/bin/env bash
set -euo pipefail

WS="/srv/shared"
GRP="editors"
MODE="2770"
FULL_USERS=("alice" "bob")
LIMITED_USERS=("runner")
LIMITED_PERMS="r-x"
DENIED_USERS=()
OTHER="---"

# Prerequisites
which setfacl getfacl
getent group "$GRP"
for u in "${FULL_USERS[@]}" "${LIMITED_USERS[@]}" "${DENIED_USERS[@]}"; do
  getent passwd "$u"
done

# Create workspace
mkdir -p "$WS"
chown root:"$GRP" "$WS"
chmod "$MODE" "$WS"

# Access ACLs
ACL="o::$OTHER"
for u in "${FULL_USERS[@]}"; do ACL+=",u:${u}:rwx"; done
for u in "${LIMITED_USERS[@]}"; do ACL+=",u:${u}:${LIMITED_PERMS}"; done
for u in "${DENIED_USERS[@]}"; do ACL+=",u:${u}:---"; done
setfacl -m "$ACL" "$WS"

# Default ACLs
DEF="u::rwx,g::rwx,o::$OTHER"
for u in "${FULL_USERS[@]}"; do DEF+=",u:${u}:rwx"; done
for u in "${LIMITED_USERS[@]}"; do DEF+=",u:${u}:${LIMITED_PERMS}"; done
for u in "${DENIED_USERS[@]}"; do DEF+=",u:${u}:---"; done
setfacl -d -m "$DEF" "$WS"

# Confirm mask
setfacl -m m::rwx "$WS"

# Verify
getfacl "$WS"
stat -c '%A %U:%G %a' "$WS"
# STOP HERE — do not create test content
```

---

## Adaptation Decision Rules

Apply when the task differs from v01:

### R1: Access policy topology

| If the task says... | Then... |
|---------------------|---------|
| "Group X should have read access" | Add `g:X:r--` to both access and default ACLs |
| "User Y is in group Z but needs extra write" | Add `u:Y:rw-` named entry (overrides group for that user) |
| "Several teams share the workspace" | Add each as named group: `g:team1:rwx,g:team2:r-x` |
| "User Y must be explicitly blocked" | Add `u:Y:---` to both access and default ACLs |
| "All authenticated users can read" | Set `other::r--` instead of `other::---` |

### R2: Permission model

| If the task says... | Then... |
|---------------------|---------|
| "Runner can only read, no execute" | Use `r--` instead of `r-x` |
| "Collaborators must not execute" | Use `rw-` instead of `rwx` |
| "Mask must limit named entries" | After setfacl, run `setfacl -m m::<mask> "$WS"` |
| "User may write only to a dropbox subdir" | Create subdir separately, set `u:<name>:rwx` on it |

### R3: Inheritance & group propagation

| If the task says... | Then... |
|---------------------|---------|
| "Deeper than 2 levels" | Default ACLs propagate recursively — no extra work |
| "Different creator identities" | Defaults + setgid work regardless of creator |
| "Sticky bit: can't delete others' files" | Use mode `3770` instead of `2770` |
| "New files must inherit group G" | Setgid (`2xxx` or `chmod g+s`) — required |
| "Group G members get auto access" | Use `g::rwx` or `g:G:rwx` in access + defaults |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Named entries show `#effective:r--` | `setfacl -m m::rwx "$WS"` |
| New files have wrong group | `chmod g+s "$WS"` or recreate with `2xxx` mode |
| `chmod` after `setfacl` broke permissions | Re-run setfacl, or always chmod first |
| Runner can still write | Add explicit `u:runner:r-x` (runner may be in `$GRP`) |
| Outsider can read | `setfacl -m o::--- "$WS"` and `setfacl -d -m o::--- "$WS"` |
| Nested subdir wrong ACLs | Re-run `setfacl -d -m ...` on parent |
| `setfacl: Operation not supported` | Filesystem needs ACL mount (`-o acl`); ext4/xfs default OK |
