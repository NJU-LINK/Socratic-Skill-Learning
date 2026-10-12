---
name: acl-permissions-inheritance
description: General starting point for solving tasks in the acl-permissions-inheritance family.
---

# acl-permissions-inheritance

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Standard Workflow

### 1. Base Directory & Setgid
- Create the shared directory, assign group ownership (`chown root:<group> <dir>`), and set base mode with setgid (`chmod 2770 <dir>`). This ensures new files and subdirectories automatically inherit the group.

### 2. Dual ACL Configuration & Explicit Denial
- Apply identical permission sets to both **access** and **default** ACLs (e.g., `setfacl -m u:<user>:<perms>` and `setfacl -d -m u:<user>:<perms>`).
- Explicitly deny unspecified users by setting `other::---` in both access (`setfacl -m o::---`) and default (`setfacl -d -m o::---`) ACLs.
- Crucially, set `default:mask::rwx` to prevent the mask from restricting named user entries on new subdirectories.

### 3. Read-Only Collaborators & Kernel Intersection
- For restricted users needing traverse/read (but not write), grant `r-x` in both access and default ACLs.
- The kernel automatically intersects the default ACL with the creation mode (e.g., `0666` for files), yielding correct effective permissions (`r--` on new files, `r-x` on new directories).

### 4. Empirical Verification
- Simulate file/subdirectory creation as a collaborator.
- Inspect resulting ACLs with `getfacl` to verify default ACL propagation and mask behavior.
- Use `su` to test actual access (read, write, execute, create) as the restricted user and an unrelated user to confirm kernel enforcement.