---
name: acl-permissions-inheritance
description: General starting point for solving tasks in the acl-permissions-inheritance family.
---

# acl-permissions-inheritance

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven ACL Configuration Patterns

### Base Directory Setup
- Create the shared directory and assign ownership (e.g., `chown root:<group> /path/to/dir`).
- Apply the setgid bit (`chmod 2770`) to ensure all new files and subdirectories automatically inherit the group ownership.

### ACL Configuration
- Use `setfacl` to define both access ACLs and default (`-d`) ACLs for inheritance.
- Use explicit named user entries (e.g., `u:alice:rwx`) rather than relying on owning group membership. Set `group::---` to prevent unintended access and `other::---`.
- Explicitly set the mask (`m::rwx`) in both access and default ACLs so named entries are not inadvertently restricted.
  ```bash
  setfacl -m u::rwx,g::---,o::---,m::rwx,u:alice:rwx,u:runner:r-x /path/to/dir
  setfacl -d -m u::rwx,g::---,o::---,m::rwx,u:alice:rwx,u:runner:r-x /path/to/dir
  ```

### Execution and Masking Behavior
- The POSIX ACL mask intersects with the file creation mode. Default ACLs are masked by the process creation mode (e.g., `0666` for regular files strips the execute bit, while `0777` for directories retains it).
- A default ACL of `r-x` automatically results in effective `r--` for regular files and `r-x` for directories, avoiding the need for post-creation permission fixes.
- If a user needs to execute scripts that collaborators might later make executable, include `x` in their default ACL entry. When a collaborator runs `chmod +x` on the file, it modifies the ACL mask to include `x`, restoring effective execute permissions without granting write access.