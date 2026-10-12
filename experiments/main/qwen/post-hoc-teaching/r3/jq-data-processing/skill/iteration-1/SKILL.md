---
name: jq-data-processing
description: >
  Transform JSON data files using jq pipelines. Handles filtering/selection of records,
  field derivation and output reshaping, scalar value normalization, and aggregation/collection
  operations. Produces correctly sorted, structured JSON output with proper artifact files
  (cmd.sh, jq_args.yaml).
---

# jq Data Processing Skill

## Overview

This skill covers JSON-to-JSON transformation tasks using `jq`. The general pattern is:
read a JSON input file, apply a pipeline that selects, normalizes, reshapes, and aggregates
records, then write structured JSON output. Tasks vary along four axes: selection/ordering
logic, field derivation/reshaping, value normalization, and aggregation/collection operations.

## General Pipeline Architecture

A jq transformation pipeline follows this structure:

```
[ input_array |
  .[] |                                    # iterate records
  # 1. NORMALIZE intermediate values       # prepare for selection
  # 2. SELECT records matching criteria    # filter
  # 3. RESHAPE into output structure       # build output objects
] |
# 4. SORT the final array                  # order output
```

Key principle: normalize values **before** selection so that predicates operate on clean data.
For example, if roles must be compared case-insensitively, normalize them first, then check
the selection predicate against the normalized values.

## Axis 1: Selection and Ordering Logic

### Filtering Patterns

**Single-field equality:**
```jq
.[] | select(.status == "active")
```

**Multi-condition predicates (AND):**
```jq
.[] | select(.status == "active" and (.roles | length > 0))
```

**Inclusion logic (value in a set):**
```jq
.[] | select(.role == "admin" or .role == "owner")
# Or with an array of allowed values:
["admin", "owner"] as $allowed | .[] | select(.role as $r | $allowed | index($r))
```

**Exclusion logic (value NOT in a set):**
```jq
# Check if email domain is NOT in blocked list
(.blocked_domains | map(normalize)) as $norm_blocked |
($email | extract_domain) as $domain |
select($norm_blocked | index($domain) | not)
```

**Predicate on derived/normalized values:**
```jq
# Normalize first, then test
(.roles | map(trim_lower)) as $nr |
select([$nr[] | select(. == "admin" or . == "owner")] | length > 0)
```

**Using `any()` for cleaner predicates:**
```jq
.[] | select(any(.roles[]; . == "admin" or . == "owner"))
```

### Sorting Patterns

**Single key ascending:**
```jq
sort_by(.username)
```

**Multiple keys, all ascending:**
```jq
sort_by(.email_domain, .username)
```

**Mixed ascending/descending:**
For descending string sort, negate the codepoints:
```jq
sort_by(.email_domain, (.username | explode | map(-.)))
```
This works because `sort_by` always sorts ascending. By negating the character codes,
the ascending sort on negated values produces descending order on the original strings.

**Descending numeric:**
```jq
sort_by(-.count)
```

**Sort after collecting into array:**
Always wrap the per-record transformation in `[ ... ]` before applying `sort_by`,
since `sort_by` operates on arrays.

## Axis 2: Field Derivation and Reshaping

### Basic Field Mapping

**Rename a field:**
```jq
{user_id: .id, name: .username}
```

**Keep fields as-is:**
```jq
{username, email}   # shorthand for {username: .username, email: .email}
```

**Combine source fields into one output field:**
```jq
{contact: "\(.username) <\(.email)>"}
```

### Nested Field Access

**Access nested objects:**
```jq
.address.city          # simple nesting
.metadata.tags[0]      # array index within nested object
```

**Extract from nested arrays:**
```jq
.roles[0]              # first element
.roles | last          # last element
.roles | .[-1]         # last element (alternative)
```

**Safe navigation with `//` (alternative operator):**
```jq
{phone: (.phone // "unknown")}    # use "unknown" if .phone is null or false
```
**Caution:** `//` triggers on `false` and `null` but NOT on empty string `""`.
For empty-string fallback, use explicit conditionals:
```jq
{phone: (if .phone == null or .phone == "" then "unknown" else .phone end)}
```

### Building Nested Output Objects

```jq
{
  user_id: .id,
  account_summary: {
    role_count: ($roles | length),
    primary_role: $roles[0],
    roles: $roles
  }
}
```

### Emitting Arrays within Records

```jq
{
  tags: [.categories[] | ascii_downcase],
  scores: [.results[].value]
}
```

### Object Manipulation

**Object → array of {key, value} pairs:**
```jq
{a: 1, b: 2} | to_entries
# => [{"key":"a","value":1}, {"key":"b","value":2}]
```

**Array of {key, value} pairs → object:**
```jq
[{key: "x", value: 10}] | from_entries
# => {"x": 10}
```

**Transform keys in-place:**
`with_entries` is shorthand for `to_entries | map(...) | from_entries`:
```jq
{a: 1, b: 2} | with_entries(.key |= ascii_upcase)
# => {"A": 1, "B": 2}
```

**Filter object properties:**
```jq
{a: 1, b: null, c: 3} | with_entries(select(.value != null))
# => {"a": 1, "c": 3}
```

**Build object from data (dynamic keys):**
The `{(.expression): value}` syntax creates an object with a computed key name:
```jq
[.[] | {(.username): .email}] | add
# => {"john": "john@example.com", "jane": "jane@example.com"}
```

This pattern is essential when field names come from data values rather than being hardcoded — for example, when grouping results by a field and using that field's value as the object key.

## Axis 3: Value Normalization

### String Operations

**Trim whitespace:**
```jq
gsub("^\\s+|\\s+$"; "")
```

**Lowercase:**
```jq
ascii_downcase
```

**Trim + lowercase (common combo):**
```jq
gsub("^\\s+|\\s+$"; "") | ascii_downcase
```

**Extract substring parts:**
```jq
# Email domain: part after @
.email | split("@") | .[1]

# Date from ISO 8601 timestamp
.last_login | split("T")[0]

# Extract with regex (jq 1.6+)
.username | capture("^(?<prefix>[a-z]+)") | .prefix
```

**String replacement:**
```jq
gsub("pattern"; "replacement")
sub("pattern"; "replacement")     # first match only
```

### Numeric Coercion

```jq
"42" | tonumber        # string to number
42 | tostring          # number to string
"3.14" | tonumber      # works for floats
```

### Boolean Derivation

```jq
{has_roles: (.roles | length > 0)}
{is_privileged: (.role == "admin" or .role == "owner")}
```

### Null Handling and Fallback Defaults

```jq
# Null-coalesce with //
.value // "default"

# Explicit null check for more complex logic
(if .phone == null or (.phone | trim | length == 0) then "unknown" else .phone | trim end)
```

### Date/Time Extraction

```jq
# ISO 8601 to YYYY-MM-DD
"2026-03-16T05:01:40.829540Z" | split("T")[0]    # => "2026-03-16"

# Extract year/month/day components
"2026-03-16T05:01:40Z" | split("T")[0] | split("-") | {year: .[0], month: .[1], day: .[2]}
```

## Axis 4: Aggregation and Collection Operations

### Per-Record Aggregation

**Count items in an array field:**
```jq
{role_count: (.roles | length)}
```

**Deduplicate and sort:**
```jq
.roles | map(trim_lower) | unique    # unique sorts ascending automatically
```

**Pick first/last from sorted list:**
```jq
.roles | unique | {first: .[0], last: .[-1]}
# With null safety:
.roles | unique | {first: (if length > 0 then .[0] else null end)}
```

### Cross-Record Aggregation

**⚠️ CRITICAL: `group_by` requires pre-sorted input**

jq's `group_by(.key)` only groups *adjacent* elements with the same key value. If the input isn't sorted by that key, identical keys that aren't adjacent end up in separate groups, producing wrong counts and aggregations — silently, with no error.

**WRONG** — will produce wrong groups if input isn't sorted by .department:
```jq
group_by(.department) | map({dept: .[0].department, count: length})
```

**CORRECT** — always sort_by before group_by:
```jq
sort_by(.department) | group_by(.department) | map({
  dept: .[0].department,
  count: length,
  members: [.[].username]
})
```

**Group by a field:**
```jq
sort_by(.department) | group_by(.department) | map({
  dept: .[0].department,
  count: length,
  members: [.[].username]
})
```

**Reduce for accumulation:**
```jq
reduce .[] as $item (0; . + $item.value)    # sum
reduce .[] as $item ({}; . + {($item.key): $item.value})  # build object
```

**Flatten nested arrays:**
```jq
[.[].tags] | flatten    # collect all tags arrays, then flatten
[.[].roles[]]           # alternative: generate all elements
```

**Collection-level summaries:**
```jq
# After group_by (remember to sort first!):
sort_by(.status) | group_by(.status) | map({
  status: .[0].status,
  total: length,
  avg_age: ([.[].age] | add / length)
})
```

### Combining Per-Record and Cross-Record

When both are needed, structure the pipeline as:
1. Per-record transformation (normalize, select, reshape) inside `[ ... ]`
2. Cross-record aggregation on the resulting array

```jq
[
  .[] |
  # per-record work
  (.roles | map(trim_lower) | unique) as $roles |
  select(.status == "active") |
  {user: .name, roles: $roles}
] |
# cross-record work (remember to sort before group_by!)
sort_by(.roles[0]) | group_by(.roles[0]) | map({
  primary: .[0].roles[0],
  users: [.[].user]
})
```

## Artifact Construction

Tasks typically require saving:

### cmd.sh
A shell script with the exact jq command including output redirection:
```bash
#!/bin/bash
jq --indent 2 'FILTER_EXPRESSION' /app/input.json > /app/output.json
```

### jq_args.yaml
YAML file with the filter and arguments, structured so the command can be reconstructed as:
`jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" input.json > output.json`

```yaml
filter: |
  [
    .[] |
    # ... jq filter body ...
  ] | sort_by(...)
args:
  - "--indent 2"
```

**Important:** The `filter` value is the jq expression only (no input/output file paths).
The `args` list contains complete flag+value pairs as separate items (e.g., `"--indent 2"`,
`"--arg name value"`).

### Parameterization with `--arg` and `--argjson`

When the task specifies configuration values (thresholds, allowed-role lists, date cutoffs,
status values), parameterize the filter so the transformation logic is separated from
data-specific configuration. The filter references `$variable_name` directly, and the
args list carries the values.

**`--arg` passes a string value:**
```yaml
filter: |
  [.[] | select(.status == $target_status)]
args:
  - "--indent 2"
  - "--arg target_status active"
```

**`--argjson` passes a JSON value (number, boolean, array, object):**
```yaml
filter: |
  [.[] | select(.score >= $min_score)]
args:
  - "--indent 2"
  - "--argjson min_score 80"
```

**Multiple parameters:**
```yaml
filter: |
  [.[] | select(.status == $target_status and (.score >= $min_score))]
args:
  - "--indent 2"
  - "--arg target_status active"
  - "--argjson min_score 80"
```

**Key distinction:** Use `--arg` when the parameter is a string. Use `--argjson` when the
parameter is a number, boolean, array, or object — `--argjson` parses the value as JSON,
so `--argjson min_score 80` makes `$min_score` a number, while `--arg min_score 80` makes
it the string `"80"`.

This parameterization pattern lets the same filter template work across different concrete
thresholds or criteria, which is essential when the spec says "selection criteria interact
with derived values or intermediate pipeline stages."

## Common Pitfalls and Solutions

1. **Normalize before compare:** Always trim/lowercase values before using them in selection
   predicates. Comparing `" Admin"` to `"admin"` will fail silently.

2. **⚠️ `group_by` requires pre-sorted input:** jq's `group_by(.key)` only groups *adjacent*
   elements with the same key. If the input isn't sorted by that key, identical keys that
   aren't adjacent end up in separate groups, producing wrong counts and aggregations —
   silently, with no error. **Always `sort_by(.key)` before `group_by(.key)`.**

3. **`unique` implies sort:** In jq, `unique` returns a sorted array. If you need a different
   sort order, apply `sort_by` after `unique`.

4. **`sort_by` with descending strings:** Use `explode | map(-.)` to negate codepoints.
   This only works for ASCII strings. For Unicode, `reverse` after ascending sort works
   for single-key sorts only — `reverse` flips *all* sort keys, so it breaks mixed-direction
   multi-key sorts (e.g., "a ascending, b descending"). For multi-key mixed-direction with
   Unicode, group_by the ascending key first, then sort_by + reverse within each group.

5. **`//` vs explicit null check:** The `//` operator triggers on both `null` and `false`.
   If you need to distinguish, use explicit `if .field == null` checks.

6. **Empty string vs null for phone:** An empty string `""` is NOT caught by `//`. Use
   explicit length check: `if .phone == null or (.phone | gsub("^\\s+|\\s+$"; "") | length == 0)`.

7. **Array wrapping for sort:** `sort_by` operates on arrays. Always collect records into
   `[ ... ]` before sorting.

8. **Variable binding with `as`:** Use `as $var` to capture intermediate values for reuse:
   ```jq
   (.roles | map(trim_lower) | unique) as $sorted_roles |
   {count: ($sorted_roles | length), first: $sorted_roles[0]}
   ```

9. **`index` returns null when not found:** `null | not` is `true`, so
   `select($array | index($value) | not)` correctly selects items where $value is absent.

10. **`--indent 2` for formatted output:** Use `--indent 2` (not `-I 2`) with jq 1.6 for
   2-space indented JSON output.

11. **`gsub` regex escaping:** In jq regex, backslashes need double-escaping in shell strings.
    Inside a single-quoted jq filter, `\\s` means `\s` in regex.

## Methodology for New Variants

When encountering a new variant of this task family:

1. **Read the input schema:** Examine the JSON structure to understand available fields,
   nesting, and data types.

2. **Map requirements to axes:**
   - What records to include/exclude? → Selection logic
   - What output fields and structure? → Field derivation
   - What value transformations? → Normalization
   - What cross-record operations? → Aggregation

3. **Build incrementally:**
   - Start with the filter/selection, verify record count
   - Add field derivation, verify structure
   - Add normalization, verify values
   - Add sorting, verify order
   - Add aggregation if needed

4. **Test edge cases:** null values, empty arrays, whitespace in strings, case variations.

5. **Save artifacts:** Write cmd.sh and jq_args.yaml, verify reconstruction command
   produces identical output.
