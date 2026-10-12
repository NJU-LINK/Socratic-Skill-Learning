---
name: jq-data-processing
description: Reusable instructions for jq-data-processing tasks.
---

# jq-data-processing

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] jq command file format
content: When saving a jq command to a command file for later replay, write only the bare jq command line with its output redirection, omitting shebangs or other shell wrapper lines so the file begins directly with `jq`.
