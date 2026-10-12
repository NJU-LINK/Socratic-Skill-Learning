---
name: jq-data-processing
description: >
  Systematic methodology for building jq-based JSON transformation pipelines
  that combine record selection/filtering, field derivation/reshaping,
  value normalization, and aggregation/collection operations. Handles tasks
  requiring multi-condition predicates, multi-key sorting (ascending and
  descending), nested field access, string/numeric/boolean coercion, fallback
  defaults, deduplication, grouping, and per-record plus cross-record
  aggregation in a single jq workflow.
---

# jq Data Processing Skill

## Overview

This skill provides a structured methodology for transforming JSON data using `jq`. Tasks in this family require building a single jq filter that combines four capability axes: selection/ordering, field derivation, value normalization, and aggregation. The approach decomposes any such task into independent sub-problems that are composed into a pipeline.

## Core Methodology

### Step 1: Analyze the Task Specification

Before writing any jq, extract these requirements from the task:

1. **Input structure**: What does each input record look like? What fields exist? What nesting?
2. **Selection criteria**: What conditions must records meet to be included? (status checks, value membership, cross-field predicates, exclusion rules)
3. **Output schema**: What fields must the output contain? What are their names and types?
4. **Value transformations**: What per-value conversions are needed? (case changes, trimming, date extraction, type coercion, fallback defaults)
5. **Aggregation needs**: What cross-element computations are required? (counts, unique lists, first/last, sums, groupings)
6. **Sort order**: What keys and directions define the final ordering?

### Step 2: Build Normalization Primitives

Normalization is the foundation. Define reusable patterns for each transformation:

```jq
# Trim whitespace from both ends
gsub("^\\s+|\\s+$"; "")

# Lowercase a string
ascii_downcase

# Trim + lowercase (common combo)
gsub("^\\s+|\\s+$"; "") | ascii_downcase

# Extract domain from email
split("@") | last | ascii_downcase

# Extract date from ISO 8601 timestamp
split("T")[0]

# Extract part of a structured string
split("pattern")[INDEX]

# Numeric coercion
tonumber  # or: if type == "string" then tonumber else . end

# Boolean derivation
. == "expected_value"  # or more complex predicates
```

**Key principle**: Normalize values BEFORE comparing, filtering, or deduplicating. The task specification may require normalization at multiple stages (e.g., normalize roles before checking if privileged, before deduplicating, and before sorting).

### Step 3: Compose the Pipeline Architecture

The standard architecture for these tasks follows this pattern:

```jq
[
  .[] |
  # Phase A: Compute derived values as variables
  (normalize_expression) as $var1 |
  (another_expression using $var1) as $var2 |
  
  # Phase B: Apply selection filter
  select(CONDITION_USING_VARS) |
  
  # Phase C: Compute output values
  (final_transform) as $output_val |
  
  # Phase D: Build output record
  {
    field1: $var1,
    field2: .source_field,
    field3: $output_val,
    nested_object: {
      sub_field: ($var2 | aggregation)
    }
  }
] | sort_by(SORT_KEYS)
```

**Why this architecture works**:
- Wrapping in `[...]` collects results into an array (needed for sorting)
- `.[]` iterates over input array elements
- `as $var` bindings compute once and reuse
- `select()` filters before building output (efficiency)
- Final `sort_by()` operates on the collected array

### Step 4: Selection and Ordering Patterns

#### Basic filtering
```jq
select(.status == "active")
```

#### Multi-condition with AND/OR
```jq
select(.status == "active" and (.roles | map(normalize) | any(. == "admin")))
```

#### Exclusion logic (NOT IN a set)
```jq
# Check if value is NOT in a normalized list
($list | map(. == $target) | any) as $found |
select($found | not)

# Or using inside/contains for substring checks
select(.value | inside($exclusion_list) | not)
```

#### Cross-field predicates
```jq
# Compare two fields after normalizing both
(.field1 | normalize) as $n1 |
(.field2 | normalize) as $n2 |
select($n1 == $n2)
```

#### Multi-key sorting
```jq
# Ascending on multiple keys
sort_by(.key1, .key2)

# Descending on a string key (trick: negate codepoints)
sort_by(.key_asc, (.key_desc | explode | map(-.)))

# Descending on a numeric key
sort_by(.key_asc, (-.key_desc))

# Complex: group then sort within groups
group_by(.group_key) | map(sort_by(.sort_key) | reverse) | add
```

**How multi-key sorting works**: When `sort_by(f)` evaluates `f` for each element and `f` produces multiple outputs via the comma operator, jq collects those outputs into an array that becomes the comparison key. So `sort_by(.email_domain, (.username | explode | map(-.)))` produces comparison keys like:
```
["company.org", [-119, -105, -108, -115, -111, -108, -104, -110, -110, -111, -110]]
```
jq then compares these arrays element-by-element: first by `.email_domain` (string, ascending), then by the negated codepoint array (array, ascending on negated values = descending on original strings). This mechanism is reliable in jq 1.6 for any comma-separated expressions inside `sort_by`.

**The `explode | map(-.)` trick**: Converts a string to an array of codepoints, negates each one. Since jq compares arrays element-by-element, negated codepoints produce reverse lexicographic order. This works for ASCII strings. For non-ASCII strings (e.g., "José", "Müller"), `explode` produces multi-byte codepoints that still compare correctly for standard Unicode ordering, but the negation may not match locale-aware collation. For in-family variants with pure ASCII usernames/emails (which is the typical case), this is safe.

**Alternative: `group_by` + `map(sort_by | reverse)` + `add`**: For 3+ sort keys, or when you need descending on multiple string keys, the comma approach gets complex. The `group_by` alternative is more readable and generalizes to any number of descending keys:
```jq
# Example: sort by email_domain ascending, then username descending
] | group_by(.email_domain)
  | map(sort_by(.username) | reverse)
  | add
```
This groups by the ascending key, then within each group sorts by the descending key and reverses. `add` flattens the array of arrays into a single array. **Important**: Use `add` instead of `flatten` here because `flatten` also descends into record-internal arrays, which would corrupt your data structure. `add` only concatenates the top-level array of arrays.

### Step 5: Field Derivation and Reshaping Patterns

#### Renaming fields
```jq
{ output_name: .input_field }
```

#### Combining multiple source fields
```jq
{ contact: "\(.username) <\(.email)>" }
```

#### Deep field access
```jq
{ value: .level1.level2.field }
# With safe navigation for optional paths
{ value: .level1.level2?.field // "default" }
```

#### Nested output objects
```jq
{
  summary: {
    count: ($items | length),
    first: ($items | first),
    all: $items
  }
}
```

#### Conditional field inclusion
```jq
{
  base_field: .value,
  optional: (if .condition then .derived else null end)
}
```

#### Building output arrays from input arrays
```jq
{
  tags: [.tags[] | normalize | select(length > 0)]
}
```

### Step 6: Value Normalization Patterns

#### String cleanup
```jq
# Trim whitespace
gsub("^\\s+|\\s+$"; "")

# Remove specific characters
gsub("[^a-zA-Z0-9]"; "")

# Replace patterns
gsub("pattern"; "replacement")

# Extract substring by position
.[0:5]  # first 5 chars
.[-3:]  # last 3 chars
```

#### Extracting parts of structured strings
```jq
# Split and take part
split("@")[1]        # domain from email
split("-")[0:3] | join("-")  # first 3 segments

# Regex capture
capture("^(?<area>\\d{3})-(?<rest>.+)$")
```

#### Numeric operations
```jq
tonumber
. + 1
. * 100 | round
(. * 100 | floor) / 100  # truncate to 2 decimals
```

#### Fallback defaults and null handling
```jq
# Simple fallback
.field // "default"

# Null-or-empty check
if .field == null or .field == "" then "default" else .field end

# Blank-after-trim check
if .field == null or (.field | gsub("^\\s+|\\s+$"; "") | length) == 0
then "unknown"
else (.field | gsub("^\\s+|\\s+$"; ""))
end

# Type-conditional
if type == "null" then "missing" else tostring end
```

### Step 7: Aggregation and Collection Operations

#### Per-record aggregation (within each input record)
```jq
# Count unique normalized values
(.roles | map(normalize) | unique | length)

# First item from sorted list
(.items | map(normalize) | sort | first)
# or
(.items | map(normalize) | sort | .[0])

# Null-safe first
(.items | map(normalize) | sort | if length > 0 then .[0] else null end)
```

#### Cross-record aggregation
```jq
# Group by a field
group_by(.category) | map({
  category: .[0].category,
  count: length,
  items: [.[] | {name, value}]
})

# Deduplicate across records
[.[] | .field] | unique

# Flatten nested arrays
[.[] | .tags[]] | unique

# Compute collection-level summary
{
  total: length,
  avg: (map(.value) | add / length),
  categories: (group_by(.cat) | map(.[0].cat))
}
```

#### Combining per-record and cross-record
```jq
# First transform each record, then aggregate
[.[] | transform_record] | group_by(.group_key) | map({
  key: .[0].group_key,
  records: .,
  summary: { count: length, total: (map(.amount) | add) }
})
```

## Common Pitfalls and Solutions

### 1. Normalization order matters
If the spec says "normalize before checking, before deduplicating, and before sorting," then normalize ONCE and reuse the normalized value through all subsequent stages. Do not normalize separately for each stage.

### 2. `any` on empty arrays
`[] | any` returns `false` in jq. This is usually the correct behavior (no items match = condition not met), but be aware of it.

### 3. `unique` already sorts
`unique` in jq both deduplicates AND sorts. Adding `| sort` after `unique` is redundant but harmless.

### 4. String interpolation in object keys
Use `"\(.var)"` for embedding variables in strings. For object construction, the key must be a literal or use `(expression):` syntax:
```jq
{ "\(.dynamic_key)": .value }  # dynamic key
{ (.field): .value }           # computed key
```

### 5. Null propagation in pipelines
`.field.subfield` errors if `.field` is null. Use optional operator `?.` or null checks:
```jq
.field?.subfield // "default"
```

### 6. Sorting with mixed ascending/descending
For numeric fields, negate: `sort_by(.asc, (-.desc))`
For string fields, use the codepoint negation trick: `sort_by(.asc, (.desc | explode | map(-.)))`
For complex cases, use `group_by` + per-group `sort_by` + `reverse`.

### 7. Phone/optional field handling pattern
```jq
# Robust pattern for "use default if null, empty, or blank"
(if .field == null or (.field | tostring | gsub("^\\s+|\\s+$"; "") | length) == 0
 then "DEFAULT"
 else (.field | tostring | gsub("^\\s+|\\s+$"; ""))
 end) as $clean_field
```

## Artifact Generation

Tasks in this family typically require saving:

1. **The jq command** (`cmd.sh`): The complete shell command including input/output redirection
2. **jq arguments** (`jq_args.yaml`): Structured representation with `filter` (the jq expression string) and `args` (list of additional jq CLI arguments like `--indent 2`)

The command reconstruction pattern:
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /app/output.json
```

### Recommended: `--from-file` Filter Storage

For complex filters with regex patterns, backslashes, or nested expressions, storing the filter directly in YAML creates a multi-layer escaping nightmare (YAML parser → shell argument → jq parser, each layer doubling backslashes). The robust pattern is to store the filter in a `.jq` file and use `--from-file` in args:

```bash
# 1. Save filter to a .jq file (single-layer escaping only)
cat > /app/filter.jq << 'JQEOF'
[.[] |
  (.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $norm_roles |
  ... rest of filter ...
] | sort_by(.email_domain, (.username | explode | map(-.)))
JQEOF

# 2. jq_args.yaml references the file — no filter escaping needed
cat > /app/jq_args.yaml << 'YAMLEOF'
filter: ""
args:
  - "--from-file"
  - "/app/filter.jq"
YAMLEOF

# 3. Reconstruction still works:
# jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > output.json
# expands to: jq --from-file /app/filter.jq "" /app/users.json > output.json
# jq ignores the empty filter string when --from-file is provided
```

**Benefits**:
- The `.jq` file contains the filter with only jq-native escaping (one level)
- The YAML is trivially simple
- The `.jq` file is independently testable with `jq -f /app/filter.jq /app/input.json`
- Scales cleanly for variants with deeper nesting, more regex patterns, or `--arg` variables

**Fallback**: For simple filters with minimal escaping, the embedded-filter approach (storing the filter string directly in YAML) is acceptable, but prefer `--from-file` for any filter with regex patterns or complex expressions.

## Verification Checklist

Before submitting, verify:
- [ ] All filter conditions are applied (status, membership, exclusion)
- [ ] Normalization is applied before comparison/dedup/sort
- [ ] Output field names match specification exactly
- [ ] Derived fields use correct format (dates, concatenated strings, etc.)
- [ ] Fallback defaults are applied for missing/null/blank values
- [ ] Aggregation counts are correct (unique vs total)
- [ ] Sort order matches specification (ascending/descending per key)
- [ ] Output is valid JSON with correct indentation
- [ ] Edge cases handled: null fields, empty arrays, blank strings
