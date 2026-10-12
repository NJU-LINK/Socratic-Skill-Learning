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

## Step 0 — Efficient Data Exploration

**Do not dump the entire input file.** Use targeted commands to understand the
data before writing the filter:

```bash
# Record count
jq 'length' /app/input.json

# Schema: all keys across all records
jq '[.[] | keys] | add | unique' /app/input.json

# First record (structure sample)
jq '.[0]' /app/input.json

# Distinct values for a field
jq '[.[].status] | unique' /app/input.json

# Null / missing field counts
jq '[.[] | select(.phone == null)] | length' /app/input.json

# Sample records matching a condition
jq '[.[] | select(.status == "active")] | .[0]' /app/input.json
```

For very large files, use `head` or `limit` inside jq:
```bash
jq '.[0:3]' /app/input.json          # first 3 records
jq '[.[] | select(...)] | length' /app/input.json  # count matches without collecting
```

## Pipeline Architecture

Build the jq filter as a single expression composed of these stages:

```
[ .[] | STAGE_FILTER | STAGE_NORMALIZE | STAGE_SELECT | STAGE_SHAPE ] | STAGE_SORT
```

1. **Iterate**: `.[]` unwraps the top-level array.
2. **Pre-filter**: cheap structural filters (e.g., `.status == "active"`) to reduce
   the working set early.
3. **Normalize**: compute derived fields and attach them with `.field = expr`
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
| Regex match | `select(.name \| test("^prefix"; "i"))` |

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

**General rule**: any time you reference a record-level field inside a nested
`[...]` array construction or inner `select`, bind it with `as $var` first.

### Multi-key sorting with mixed directions

jq's `sort_by` is **stable** and always ascending. For mixed ascending/descending
sorts, chain stable sorts in **reverse priority order**:

```jq
# Sort by email_domain ASC, then username DESC:
| sort_by(.username) | reverse   # secondary key descending first
| sort_by(.email_domain)         # primary key ascending last (stable)
```

For descending on a numeric key, use negation: `sort_by(-.score)`.

For three or more keys, apply from lowest-priority to highest-priority:
```jq
# Sort by region ASC, department ASC, salary DESC:
| sort_by(-.salary)
| sort_by(.department)
| sort_by(.region)
```

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

### Combining multiple source fields into one

```jq
full_name: "\(.first_name) \(.last_name)"
address_line: [.street, .city, .state, .zip] | join(", ")
```

### Emitting nested arrays or flattening

```jq
# Build an array from nested data
tags: [.labels[] | {key: ., source: "auto"}]

# Flatten nested arrays
all_items: [.orders[].items[] | .name]
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

For more complex date parsing, use `capture` with a regex:
```jq
.last_login | capture("^(?<d>\\d{4}-\\d{2}-\\d{2})") | .d
```

For full datetime formatting when `strptime`/`strftime` are available (jq 1.6+):
```jq
.last_login | strptime("%Y-%m-%dT%H:%M:%SZ") | strftime("%Y-%m-%d")
```

### Numeric coercion and boolean derivation

```jq
(.count | tonumber)
(.field | test("yes"; "i"))       # boolean from string
(.price | tostring)               # number to string
```

### String cleanup and extraction

```jq
# Extract part of a structured string
(.filename | capture("^(?<base>.+)\\.(?<ext>[^.]+)$"))

# Replace internal whitespace
(.description | gsub("\\s+"; " "))
```

## 4. Aggregation and Collection Operations

### Deduplication and sorting within a record

```jq
.normalized_roles = (
  [.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] | unique
)
```

`unique` in jq already sorts ascending. Adding explicit `| sort` is harmless
and clarifies intent.

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

### Cross-record grouping and aggregation

Use `group_by` on the collected array, then `map` each group to a summary:

```jq
[.[] | select(.status == "active")]
| group_by(.department)
| map({
    department: .[0].department,
    headcount: length,
    avg_salary: ([.[].salary] | add / length)
  })
| sort_by(.department)
```

**Important**: `group_by(.field)` requires the input array to already be sorted
by `.field`. It groups consecutive runs of equal values. If the input is not
sorted, sort it first:

```jq
sort_by(.department) | group_by(.department)
```

### Flattening and rebuilding arrays

```jq
# Flatten: collect a field from all sub-items
all_emails: [.users[].email]

# Deduplicate across records
[.[] | .tags[]] | unique
```

### Collection-level summaries

```jq
# Min, max, average
{
  min_score: ([.[].score] | min),
  max_score: ([.[].score] | max),
  avg_score: ([.[].score] | add / length)
}
```

### Combining per-record transformation with cross-record aggregation

When the task requires both per-record reshaping and a final summary, do the
per-record work first, then aggregate the result:

```jq
[.[] | { user_id: .id, dept: .department, salary: (.pay | tonumber) }]
| {
    records: .,
    summary: {
      total: length,
      by_dept: (group_by(.dept) | map({dept: .[0].dept, count: length}))
    }
  }
```

## jq Flags Quick Reference

| Flag | Purpose | When to use |
|------|---------|-------------|
| *(default)* | JSON in, JSON out, 2-space indent | Most tasks |
| `-r` / `--raw-output` | Output strings without quotes | Producing plain text, CSV, or shell-consumable output |
| `-R` / `--raw-input` | Read each line as a string instead of JSON | Processing log files or line-delimited text |
| `-s` / `--slurp` | Wrap all inputs into a single array | Multiple JSON objects in one file, or combining files |
| `-c` / `--compact-output` | One-line JSON output | When the task requires compact format |
| `--sort-keys` | Alphabetically sort object keys | Deterministic key order for comparison |
| `--indent N` | Use N spaces for indentation | Non-default indentation (e.g., 4 spaces) |
| `--arg name val` | Bind `$name` to string `val` | Parameterizing filters with external values |
| `--argjson name val` | Bind `$name` to parsed JSON `val` | Passing numbers, booleans, or arrays as parameters |
| `--slurpfile name file` | Bind `$name` to parsed JSON from file | Looking up reference data |

### Using `--arg` for parameterized values

When filter logic depends on external values (thresholds, role names, dates),
pass them via `--arg` rather than hardcoding. This makes the filter reusable
and avoids quoting issues:

```bash
jq --arg status "active" --arg role "admin" \
   '[.[] | select(.status == $status) | select([.roles[] | select(. == $role)] | length > 0)]' \
   /app/input.json
```

In `jq_args.yaml`, each `--arg` becomes two list items:
```yaml
args: ["--arg", "status", "active", "--arg", "role", "admin"]
```

## Input Shape Handling

Not all inputs are top-level JSON arrays. Adapt the pipeline entry point:

| Input shape | Approach |
|------------|----------|
| `[ {...}, {...} ]` (array) | `.[] \| ...` |
| `{ "data": [...] }` (wrapped array) | `.data[] \| ...` |
| Multiple JSON objects, one per line | Use `--slurp` flag, then `.[] \| ...` |
| `{ ... }` (single object) | Omit `.[]`; work on `.` directly |
| Multiple files | `jq 'filter' file1.json file2.json` or `--slurp` |

For `--slurp` mode, the `args` field in `jq_args.yaml` includes it:
```yaml
args: ["--slurp"]
```

## Artifact Generation

### Output JSON

Always produce indented JSON (jq defaults to 2-space indent). If the task
requires a different indentation, use `--indent N`.

### cmd.sh

Write the exact jq command including input and output redirection:
```bash
jq 'FILTER_EXPRESSION' /app/input.json > /app/output.json
```

For multiline filters in cmd.sh, use single quotes — they allow embedded
double quotes and newlines without escaping:
```bash
jq '[
  .[] |
  select(.status == "active") |
  ...
]' /app/input.json > /app/output.json
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
  trailing newline). The filter can be multiline for readability.
- `args`: list of extra jq flags. Each flag and its value is a separate string.
  Examples:
  - No extra args: `args: []`
  - With slurp: `args: ["--slurp"]`
  - With parameters: `args: ["--arg", "status", "active"]`
  - Combined: `args: ["--slurp", "--arg", "role", "admin"]`

**YAML block scalar (`|-`) preserves content literally** — no YAML escaping
of backslashes or quotes. The filter string passes through `yq -r` unchanged,
and bash `"$(...)"` preserves it through command substitution. This means
jq receives the exact characters you wrote in the YAML file.

**Important**: Test the reconstruction command explicitly. Diff its output
against the primary output to confirm they are byte-identical.

## Verification Checklist

Before submitting, verify:

1. **Record count**: Does the output have the expected number of records?
   Cross-check with `jq 'length'`.
2. **Field presence**: Every output record has all required fields.
   Use `jq '.[0] | keys'` to spot-check.
3. **Sort order**: Walk through consecutive pairs to confirm multi-key sort.
4. **Normalization**: Spot-check that trimmed/lowercased values appear correct.
5. **Null/blank fallback**: Confirm default values appear where source is missing.
6. **Reproducibility**: Run the reconstruction command from `jq_args.yaml` and
   diff against the primary output — they must be identical.
7. **Format**: Output is valid JSON with correct indentation.
8. **cmd.sh replay**: Run `bash /app/cmd.sh` and diff its output too.

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Cannot index string with string "X"` | `.field` used inside nested `select` where `.` is a string | Bind with `as $var` before entering nested iteration |
| `null` errors on string ops | Phone/field is `null`, not missing | Check `== null` before calling `gsub` / `split` |
| Wrong sort direction | `sort_by` is always ascending | Chain stable sorts in reverse priority; use `reverse` |
| `group_by` produces wrong groups | Input not sorted by grouping key | `sort_by(.key) \| group_by(.key)` |
| Duplicate roles in output | Missing dedup step | Use `unique` after normalization |
| Shell quoting errors in cmd.sh | Unescaped `'` inside single-quoted filter | Use multiline single-quoted heredoc or `jq_args.yaml` |
| YAML filter escaping issues | Using quoted YAML scalar instead of block scalar | Use `filter: \|-` (block scalar), never `"..."` for filters |
| Reconstruction command fails | `args` list items not split correctly | Each flag and value must be a separate YAML list item |
