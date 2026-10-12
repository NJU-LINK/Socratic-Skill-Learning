---
name: acl-permissions-inheritance
description: General starting point for solving tasks in the acl-permissions-inheritance family.
---

# acl-permissions-inheritance

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Workflow

1. **Base Directory & Setgid Initialization**: Create the target directory, assign group ownership (e.g., `chown root:editors`), and apply the setgid bit (e.g., `chmod 2770`) *before* configuring ACLs to ensure proper group propagation.
2. **Dual ACLs & Explicit Masks**: Apply both access and default ACLs (`setfacl -m` and `setfacl -d -m`). Always set an explicit default mask (e.g., `d:m::rwx`) to prevent automatic restriction. For read/execute semantics, use `r-x` defaults; the kernel automatically masks inherited permissions based on creation mode (regular files inherit `r--`, directories `r-x`).
3. **Ephemeral Verification & Cleanup**: Test inheritance by creating temporary files/directories and inspecting with `getfacl`. Note that regular files (mode `0666`) do not inherit the execute bit; apply `chmod +x` post-creation if needed. **Crucially, remove all test artifacts immediately** to avoid leaving unwanted content in the workspace.