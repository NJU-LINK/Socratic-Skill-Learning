---
name: flask
description: Reusable instructions for flask tasks.
---

# flask

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Relative persistence paths
content: When a task specifies file-based persistence relative to the current working directory, use a bare relative path in each connection call rather than resolving to an absolute path at module load time.
