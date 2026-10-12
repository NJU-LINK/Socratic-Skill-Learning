---
name: jq-data-processing
description: General starting point for solving tasks in the jq-data-processing family.
---

# jq-data-processing

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

## Filtering vs. Aggregation in jq
When a task requires filtering records based on a condition (e.g., "include only accounts with a privileged role") while also computing summary fields (e.g., "list all roles", "role count"):
1. Compute the full normalized/deduplicated attribute list first.
2. Use the full list for summary and aggregation fields.
3. Separately evaluate the filter predicate (e.g., `any(. == "admin" or . == "owner")`) to determine record inclusion.

DO NOT destructively filter the attribute array before computing summaries unless the prompt explicitly restricts the summary to the filtered subset.

## Proven Patterns
For complex operations like multi-key sorting, string trimming, and YAML serialization of filters, read [references/jq-patterns.md](references/jq-patterns.md).
