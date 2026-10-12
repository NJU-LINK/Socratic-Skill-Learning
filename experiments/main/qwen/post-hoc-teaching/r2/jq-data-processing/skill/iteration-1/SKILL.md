---
name: jq-data-processing
description: >
  Transform JSON data files using jq pipelines. Covers record selection with
  multi-condition predicates, field derivation and reshaping (renaming, nesting,
  combining), value normalization (string cleanup, type coercion, date parsing,
  fallback defaults), aggregation and collection operations (grouping, counting,
  deduplication, cross-record summaries), and multi-key sorting with mixed
  directions. Produces output artifacts including the transformed JSON, a shell
  command script, and a YAML argument manifest.
---

# jq Data Processing Skill

## Overview

This skill covers transforming JSON data using `jq` command-line tool. Tasks involve reading a JSON input file, applying a complex transformation pipeline, and writing structured output. The pipeline typically combines filtering, per-record transformation, aggregation, and sorting.

## Core Methodology

### 1. Analyze the Input Data

Before writing any jq code, inspect the input:

```bash
# Check structure and size
jq 'length' /app/input.json
jq '.[0]' /app/input.json          # first record
jq '.[0] | keys' /app/input.json   # field names
jq '[.[] | keys] | map(length) | unique' /app/input.json  # check schema consistency
```

Identify:
- Record-level fields and their types (string, number, array, object, null)
- Which fields are nested arrays or objects
- Which fields may be null or missing
- Value patterns (timestamps, emails, role names with inconsistent casing/whitespace)

### 2. Decompose the Requirements

Break the task into independent transformation stages:

| Stage | Purpose | Typical jq Operations |
|-------|---------|----------------------|
| **Selection** | Filter which records to include | `select(...)`, `any(...)`, `IN(...)` |
| **Normalization** | Clean/standardize values before comparison | `gsub("^\\s+\|\\s+$";"")`, `ascii_downcase`, `split`, `ltrimstr`/`rtrimstr` |
| **Derivation** | Build output fields from input | Object construction `{key: expr}`, string interpolation |
| **Aggregation** | Compute per-record or cross-record summaries | `group_by`, `reduce`, `map`, `unique`, `length` |
| **Ordering** | Sort the output array | `sort_by`, `reverse` (stable sort chaining) |

### 3. Build the Pipeline Incrementally

Always test each stage before combining:

```bash
# Test selection alone
jq '[.[] | select(.status == "active")] | length' input.json

# Test normalization alone
jq '[.[] | .roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique] | .[0:3]' input.json

# Test derivation on a single record
jq '.[0] | {user_id: .id, name: .username}' input.json
```

## Variation Dimension Patterns

### Selection and Ordering Logic

**Single-condition filter:**
```jq
.[] | select(.status == "active")
```

**Multi-condition predicate (AND):**
```jq
.[] | select(.status == "active" and (.roles | any(. == "admin")))
```

**Multi-condition predicate (OR / inclusion-exclusion):**
```jq
.[] | select(
  (.roles | any(. == "admin" or . == "owner")) and
  (.blocked | all(. != .email_domain))
)
```

**Exclusion via membership test:**
```jq
# Check if value is NOT in an array
(.blocked_domains | map(normalize) | any(. == $target) | not)
# Or equivalently:
([$blocked[] | select(. == $target)] | length == 0)
```

**Selection interacting with derived values:**
```jq
# Normalize first, then filter on normalized values
(.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique) as $norm |
select($norm | any(. == "admin"))
```

**Multi-key sorting with mixed directions:**

jq's `sort_by` is stable and always ascending. For descending secondary keys, chain sorts:

```jq
# Sort by field_a ascending, then field_b descending:
sort_by(.field_b) | reverse | sort_by(.field_a)
```

This works because stable sort preserves the secondary ordering when primary keys are equal.

**Sorting by computed/derived values:**
```jq
sort_by(.email | split("@") | last | ascii_downcase)
```

### Field Derivation and Reshaping

**Simple field rename:**
```jq
{user_id: .id, name: .username}
```

**String interpolation for composite fields:**
```jq
{contact: "\(.username) <\(.email)>"}
```

**Extracting from nested arrays:**
```jq
{primary_role: (.roles | map(normalize) | unique | .[0])}
```

**Deep field access with null safety:**
```jq
{value: .nested.deep.field // "default"}
{value: (.nested.deep.field // null)}
```

**Building nested output objects:**
```jq
{
  user_id: .id,
  account_summary: {
    role_count: (.roles | length),
    primary_role: (.roles | .[0] // null),
    roles: .roles
  }
}
```

**Combining multiple source fields into one:**
```jq
{full_name: "\(.first_name) \(.last_name)"}
{address: {street: .street, city: .city, zip: .zip}}
```

**Conditional field inclusion:**
```jq
# Always include field, but with fallback
{phone: (if ((.phone // "") | gsub("^\\s+|\\s+$";"") | length) == 0 then "unknown" else (.phone | gsub("^\\s+|\\s+$";"")) end)}
```

### Value Normalization

**Trim whitespace:**
```jq
gsub("^\\s+|\\s+$"; "")
```

**Lowercase:**
```jq
ascii_downcase
```

**Combined trim + lowercase (most common pattern):**
```jq
gsub("^\\s+|\\s+$"; "") | ascii_downcase
```

**Extract part of structured string:**
```jq
# Email domain: part after @
.email | split("@") | last | ascii_downcase

# Date from ISO 8601 timestamp
.last_login | split("T") | .[0]

# Extract number from string
.phone | gsub("[^0-9]"; "")
```

**Numeric coercion:**
```jq
.value | tonumber
.value | tostring
```

**Boolean derivation:**
```jq
(.roles | length > 0)
(.status == "active")
```

**Fallback defaults and null handling:**
```jq
# Null coalescing
.field // "default"

# Handle null, missing, or blank
(if ((.field // "") | gsub("^\\s+|\\s+$";"") | length) == 0 then "default" else (.field | gsub("^\\s+|\\s+$";"")) end)

# Null propagation (keep null if source is null)
.field // null
```

**Per-value formatting:**
```jq
# Round to N decimal places
.value * 100 | round / 100

# Pad strings
.id | tostring | ("00000" + .)[-5:]
```

### Aggregation and Collection Operations

**Per-record counting:**
```jq
{role_count: (.roles | unique | length)}
```

**Per-record first/last from sorted collection:**
```jq
.roles | sort | .[0]      # first alphabetically
.roles | sort | .[-1]     # last alphabetically
```

**Deduplication:**
```jq
.roles | map(normalize) | unique   # unique also sorts
# Or without sorting:
.roles | reduce .[] as $r ([]; if (. | index($r)) then . else . + [$r] end)
```

**Grouping records:**
```jq
group_by(.department) | map({
  department: .[0].department,
  count: length,
  members: [.[].username]
})
```

**Cross-record aggregation:**
```jq
# Sum across all records
[.[].salary] | add

# Average
[.[].salary] | (add / length)

# Group then aggregate
group_by(.status) | map({
  status: .[0].status,
  count: length,
  avg_salary: ([.[].salary] | add / length)
})
```

**Flattening nested arrays:**
```jq
[.[].roles | .[]] | unique   # collect all roles from all records, deduplicate
```

**Building lookup structures:**
```jq
# Create an index by key
INDEX(.[]; .id)    # {1: {record}, 2: {record}, ...}
```

**Combining per-record transformation with cross-record aggregation:**
```jq
# First compute per-record values, then aggregate
[.[] | {.id, role_count: (.roles | unique | length)}] |
{
  total_roles: (map(.role_count) | add),
  max_roles: (map(.role_count) | max),
  records: .
}
```

## Output Artifact Construction

Tasks require specific output files. The standard pattern:

### 1. The jq Filter

Build as a single jq expression string. Use `as` bindings to avoid recomputation:

```jq
[.[] |
  # Bind normalized values
  (.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique) as $norm_roles |
  (.email | split("@") | last | ascii_downcase) as $email_domain |
  
  # Filter
  select(
    .status == "active" and
    ($norm_roles | any(. == "admin" or . == "owner")) and
    # ... more conditions
  ) |
  
  # Transform
  {
    user_id: .id,
    # ... output fields
  }
] |
# Post-processing: sort, limit, etc.
sort_by(.field_a) | reverse | sort_by(.field_b)
```

### 2. cmd.sh

Save the exact command including output redirection:

```bash
#!/bin/bash
jq '<filter_expression>' /app/input.json > /app/output.json
```

### 3. jq_args.yaml

Separate the filter and arguments for programmatic reconstruction:

```yaml
filter: '<jq filter expression as string>'
args: []
```

The command is reconstructed as:
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /app/output.json
```

**Important YAML encoding notes:**
- Use `yq` to generate the YAML to handle escaping correctly
- The filter string may contain backslashes, quotes, and special characters
- `args` is a list of individual argument tokens (flag and value as separate items when applicable)
- jq's default output is 2-space indented; for default indentation leave `args` empty
- If non-default indentation is needed and jq 1.7+ is available, use `args: ['--indent', 'N']`
- jq 1.6 does NOT support `--indent`; it always outputs 2-space indentation with no override

## Common Pitfalls

1. **Normalization order matters**: Normalize values BEFORE comparison, BEFORE deduplication, and BEFORE sorting. The task specification defines the order explicitly.

2. **`unique` sorts**: In jq, `unique` both deduplicates AND sorts. If you need deduplication without sorting, use `reduce` with `index`.

3. **Stable sort chaining**: For multi-key sort with mixed directions, sort by the least-significant key first (reversed if descending), then by more significant keys. jq's sort is stable.

4. **Null handling**: Use `//` (alternative operator) for null coalescing. Remember that `null | ascii_downcase` errors; always guard with `// ""` first.

5. **Array membership**: `any(. == $value)` tests membership. For checking non-membership: `any(. == $value) | not` or `[..., select(. == $value)] | length == 0`.

6. **String interpolation in jq**: Use `"\(.field)"` syntax. The parentheses are required around expressions.

7. **`gsub` regex**: jq uses PCRE-style regex. `^\\s+|\\s+$` matches leading/trailing whitespace. Remember to double-escape backslashes in shell strings.

8. **No `trim` built-in**: jq has NO `trim` function in any version. Always use `gsub("^\\s+|\\s+$";"")` for trimming whitespace. Variants `ltrimstr`/`rtrimstr` exist but only strip exact string prefixes/suffixes, not whitespace classes.

9. **jq version differences (1.6 vs 1.7+)**:
   - `--indent N` flag: available in jq 1.7+, NOT in jq 1.6. Check with `jq --version`.
   - `IN(expr; values)`: available in jq 1.6+ but syntax differs — `IN(.x; "a","b")` works; `IN("a","b")` on input `"a"` does NOT work as expected.
   - `try-catch` syntax: jq 1.7 added `try EXP catch EXP`; jq 1.6 only has `try EXP`.
   - `@base64d`: available in jq 1.6+.
   - `foreach`: available in both, but behavior with `reduce` interactions differs subtly.
   - When in doubt, check `jq --version` and `jq --help` before relying on newer features.

## Verification Checklist

Before finalizing output:

- [ ] Correct number of records (verify filter logic)
- [ ] All required output fields present with correct names
- [ ] Field values correctly normalized (spot-check several records)
- [ ] Sorting verified (check first/last records, check within-group ordering)
- [ ] Edge cases handled: null values, blank strings, empty arrays
- [ ] Output JSON properly formatted (indentation matches requirement)
- [ ] cmd.sh produces identical output when run
- [ ] jq_args.yaml round-trips correctly through the reconstruction command
