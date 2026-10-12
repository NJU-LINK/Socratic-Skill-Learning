---
name: jq-data-processing
description: General starting point for solving tasks in the jq-data-processing family.
---

# jq-data-processing

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven jq Patterns

### Mixed-Direction Sorting
Exploit jq's stable `sort_by` for mixed-direction multi-key ordering (e.g., A ascending, B descending). Sort by the secondary key, reverse, then sort by the primary key:
```jq
sort_by(.B) | reverse | sort_by(.A)
```

### String Normalization & Variable Binding
For case-insensitive and whitespace-tolerant matching, trim and downcase, and bind to a variable to avoid redundant computation.
*Note: Avoid shorthand regex classes like `\s` or `\d` when jq filters are embedded in YAML or shell scripts, as backslashes get mangled. Use POSIX classes like `[[:space:]]` or explicit ranges like `[0-9]`.*
```jq
(.field | map(gsub("^[[:space:]]+|[[:space:]]+$"; "") | ascii_downcase)) as $norm_field |
...
```
Use `unique` on the normalized array to get sorted, deduplicated results.

### Safely YAML-Encode Filters
When writing complex jq filters to `jq_args.yaml`, pass the raw filter through a shell variable into `yq` to handle escaping:
```bash
FILTER_CONTENT=$(cat filter.txt)
yq -y -n --arg filter "$FILTER_CONTENT" '{filter: $filter, args: []}' > jq_args.yaml
```

### Stage-wise Count Verification
Run lightweight count queries at each filter stage to validate the pipeline before finalizing:
```bash
jq '[.[] | select(.status == "active")] | length' data.json
jq 'final_filter | length' data.json
```
Verify counts reconcile (e.g., total − excluded = final) to catch logic errors early.