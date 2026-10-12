---
name: jq-data-processing
description: >
  Transform JSON data files using jq pipelines: filter records by multi-field
  predicates, normalize and derive values, reshape record structures, aggregate
  across items, and produce sorted, formatted JSON output along with reproducible
  command artifacts (cmd.sh and jq_args.yaml).
---

# jq Data Processing

## Overview

You are given a JSON input file (typically an array of records) and must use `jq`
to produce a transformed JSON output file. You also produce two reproducibility
artifacts: a shell script (`cmd.sh`) and a YAML argument file (`jq_args.yaml`).

## Pipeline Architecture

Build the jq filter as a single expression composed of these stages:

```
[ .[] | STAGE_FILTER | STAGE_NORMALIZE | STAGE_SELECT | STAGE_SHAPE ] | STAGE_SORT
```

1. **Iterate**: `.[]` unwraps the top-level array.
2. **Pre-filter**: cheap structural filters (e.g., `.status == "active"`) to reduce
   the working set early.
3. **Normalize**: compute derived fields and attach them with `|= .field = expr`
   so downstream stages can reference them.
4. **Select**: apply all predicate logic using normalized values.
5. **Shape**: build the output record with `{ ... }`.
6. **Sort**: apply to the collected output array.

## 1. Selection and Ordering Logic

### Filtering patterns

| Need | jq pattern |
|------|-----------|
| Exact match | `select(.field == "value")` |
| Inclusion in set | `select(.field == ("a" or "b" or "c"))` or `select(.field as $f \| ["a","b"] \| any(. == $f))` |
| Exclusion | `select(condition \| not)` |
| Cross-field predicate | `select(.a == .b)` — but see **Variable Binding** below |
| Nested array condition | `select([.arr[] \| select(test("pattern"))] \| length > 0)` |

### Variable binding (critical pitfall)

When comparing a record field against values produced by iterating a nested array
inside `select`, the inner iteration changes `.` context. **Always bind outer
values to variables first:**

```jq
.email_domain as $ed
| select(([.blocked_domains[] | select(. == $ed)] | length) == 0)
```

Without `as $ed`, the `.email_domain` reference inside the inner `select` would
try to index into each blocked-domain string, causing a type error.

### Multi-key sorting with mixed directions

jq's `sort_by` is **stable** and always ascending. For mixed ascending/descending
sorts, chain stable sorts in **reverse priority order**:

```jq
# Sort by email_domain ASC, then username DESC:
| sort_by(.username) | reverse   # secondary key descending first
| sort_by(.email_domain)         # primary key ascending last (stable)
```

For descending on a numeric key, use negation: `sort_by(-.score)`.

## 2. Field Derivation and Reshaping

### Renaming fields

```jq
{ user_id: .id, username: .username }
```

### Computed fields

```jq
contact: "\(.username) <\(.email)>"          # string interpolation
email_domain: (.email | split("@")[1] | ascii_downcase)  # extraction
```

For string concatenation without interpolation:
```jq
contact: (.username + " <" + .email + ">")
```

### Nested output objects

```jq
account_summary: {
  role_count: (.normalized_roles | length),
  primary_role: (if (.normalized_roles | length) > 0
                 then .normalized_roles[0] else null end),
  roles: .normalized_roles
}
```

### Deeper field access

Use `.a.b.c` for nested access. Guard against missing paths:
```jq
(.metadata.labels.priority // "default")
```

## 3. Value Normalization

### Whitespace trimming

jq 1.6 has no built-in `trim`. Use gsub:
```jq
gsub("^\\s+|\\s+$"; "")
```

### Case normalization

```jq
ascii_downcase    # or ascii_upcase
```

### Null and blank handling with defaults

```jq
phone: (if .phone == null
           or (.phone | gsub("^\\s+|\\s+$"; "")) == ""
        then "unknown"
        else (.phone | gsub("^\\s+|\\s+$"; "")) end)
```

**Order matters**: check `null` before calling string functions.

### Date extraction from ISO 8601

```jq
.last_login | split("T")[0]     # "2026-03-16T05:01:40Z" → "2026-03-16"
```

For more complex date parsing, use `strptime` / `strftime` if available, or
`capture` with a regex:
```jq
.last_login | capture("^(?<d>\\d{4}-\\d{2}-\\d{2})") | .d
```

### Numeric coercion and boolean derivation

```jq
(.count | tonumber)
(.field | test("yes"; "i"))       # boolean from string
```

## 4. Aggregation and Collection Operations

### Deduplication and sorting within a record

```jq
.normalized_roles = (
  [.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] | unique | sort
)
```

`unique` in jq already sorts; explicit `sort` is redundant but makes intent clear.

### Counting

```jq
role_count: (.normalized_roles | length)
```

### First-element / fallback

```jq
primary_role: (if (.normalized_roles | length) > 0
               then .normalized_roles[0] else null end)
```

Or using alternative operator:
```jq
primary_role: (.normalized_roles[0] // null)
```

### Cross-record aggregation

When you need group-level summaries, wrap the per-record pipeline inside
`group_by` or use `[.[] | ...] | group_by(.key) | map({...})`.

## Artifact Generation

### Output JSON

Always produce indented JSON (jq defaults to 2-space indent).

### cmd.sh

Write the exact jq command including input and output redirection:
```bash
jq 'FILTER_EXPRESSION' /app/input.json > /app/output.json
```

### jq_args.yaml

This file must allow reconstruction via:
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) \
   "$(yq -r '.filter' /app/jq_args.yaml)" \
   /app/input.json > /app/output.json
```

Structure:
```yaml
filter: |-
  THE_JQ_FILTER_EXPRESSION
args: []
```

- `filter`: the complete jq filter as a YAML block scalar (use `|-` to strip
  trailing newline).
- `args`: list of extra jq flags (e.g., `["--slurp", "--arg", "key", "val"]`).
  Empty list when no extra arguments are needed.

**Important**: When the filter contains `"` characters (for jq string literals),
the reconstruction still works because `$(yq -r '.filter' ...)` inside double
quotes in bash performs command substitution without re-interpreting quotes in
the result.

## Verification Checklist

Before submitting, verify:

1. **Record count**: Does the output have the expected number of records?
   Cross-check with a quick Python one-liner or manual count.
2. **Field presence**: Every output record has all required fields.
3. **Sort order**: Walk through consecutive pairs to confirm multi-key sort.
4. **Normalization**: Spot-check that trimmed/lowercased values appear correct.
5. **Null/blank fallback**: Confirm default values appear where source is missing.
6. **Reproducibility**: Run the reconstruction command from `jq_args.yaml` and
   diff against the primary output — they must be identical.
7. **Format**: Output is valid JSON with 2-space indentation.

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Cannot index string with string "X"` | `.field` used inside nested `select` where `.` is a string | Bind with `as $var` before entering nested iteration |
| `null` errors on string ops | Phone/field is `null`, not missing | Check `== null` before calling `gsub` / `split` |
| Wrong sort direction | `sort_by` is always ascending | Chain stable sorts in reverse priority; use `reverse` |
| Duplicate roles in output | Missing dedup step | Use `unique` after normalization |
| Shell quoting errors in cmd.sh | Unescaped `'` inside single-quoted filter | Use `jq_args.yaml` reconstruction path |
