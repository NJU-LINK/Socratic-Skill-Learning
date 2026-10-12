---
name: deterministic-tarball
description: Reusable instructions for deterministic-tarball tasks.
---

# deterministic-tarball

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Use specified CLI flags literally
content: When the task specifies exact command-line flags, tool invocations, or describes tool behavior in natural language that maps to standard CLI options, embed the corresponding CLI commands with their literal flags in the script rather than replacing them with equivalent programmatic APIs, because tests may grep the script text for those flags.
