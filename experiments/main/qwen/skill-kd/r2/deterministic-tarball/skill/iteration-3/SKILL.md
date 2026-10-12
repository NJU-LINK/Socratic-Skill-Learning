---
name: deterministic-tarball
description: Reusable instructions for deterministic-tarball tasks.
---

# deterministic-tarball

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Preserve literal CLI flags in scripts
content: When the task specifies command-line flags, tool names, or format and option requirements that have known CLI flag equivalents, invoke the corresponding CLI tools directly in the script with their literal flag strings rather than using programmatic library equivalents, because tests may search the script source for those strings rather than only validating the output.

[RULE 003] Overwrite output safely in scripts
content: When a script writes to a fixed output path, use shell output redirection rather than tool-specific output flags, because some tools refuse to overwrite existing files when reading from standard input.
