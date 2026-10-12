---
name: jq-data-processing
description: General starting point for solving tasks in the jq-data-processing family.
---

# jq-data-processing

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.



## Common Pitfalls

- **jq_args.yaml args list**: When constructing the `args` list, each item must be a single complete argument string. Combine flags and their values into one string (e.g., `["--indent 2"]` or `["--indent=2"]`). Do NOT split them into separate list elements (e.g., `["--indent", "2"]`), as validation checks require every item to start with a hyphen.

## References

- [jq Processing Patterns](references/jq-patterns.md): Proven patterns for sorting, deduplication, filtering, and YAML/bash integration. Read this when implementing complex selection, ordering, or aggregation logic.
