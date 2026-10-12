---
name: organization-json-generator
description: Reusable instructions for organization-json-generator tasks.
---

# organization-json-generator

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Preserve reference identifiers verbatim
content: When converting relational source data into a nested output and a field contains identifiers that reference records in another table, preserve those identifiers verbatim in the output rather than resolving them to display names or other human-readable values, unless the target schema explicitly requires resolved values.
