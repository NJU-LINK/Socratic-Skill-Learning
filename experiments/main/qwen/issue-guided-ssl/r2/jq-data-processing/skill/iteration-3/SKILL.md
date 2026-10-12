---
name: jq-data-processing
description: >
  Reusable patterns for JSON data transformation pipelines using jq, covering
  record selection with multi-condition predicates, field derivation and
  reshaping, value normalization (trimming, case folding, null handling, date
  extraction), collection operations (deduplication, aggregation, array
  manipulation), mixed-direction sorting, and escaping-safe filter design across
  YAML/bash/jq layers.
---

# jq Data Processing Skill

## Overview

This skill covers building complex jq pipelines that filter, transform, normalize,
aggregate, and sort JSON data. It addresses common pitfalls around escaping across
multiple serialization layers, mixed-direction sorting, and structuring intermediate
computations.

## Core Patterns

### 1. Mixed-Direction Sorting via Stable-Sort Chaining

jq's `sort_by` only sorts ascending with no descending flag. However, jq's sort
is **stable**, enabling mixed-direction ordering by chaining sorts from least
significant to most significant key:

```jq
# To sort by field_A ascending, then field_B descending:
# Step 1: Sort by secondary key in its target direction
| sort_by(.field_B) | reverse
# Step 2: Sort by primary key ascending (stable preserves step 1 order)
| sort_by(.field_A)
```

**Why this works**: A stable sort preserves the relative order of equal elements.
When `sort_by(.field_A)` encounters records with the same `field_A`, it keeps
them in the order established by the previous sort (descending `field_B`).

**Generalization**: For N sort keys with mixed directions, chain from the
least-significant key to the most-significant, applying `reverse` after any
sort that needs descending order. The final sort (most significant key) should
NOT be reversed if it needs ascending order.

**Do NOT** attempt to negate strings or use custom comparators — jq 1.6 does
not support them.

### 2. Escaping-Safe Filter Design Across YAML → Bash → jq Layers

When a jq filter passes through multiple layers (YAML storage → `yq -r` output
→ bash command substitution → jq parser), certain characters create fragile
escaping chains.

#### Backslash Risk
Using `\s` in jq regex requires `\\s` in jq source. But `\\` inside bash
double-quoted `"$(…)"` may collapse to `\`. This creates layer-dependent
behavior.

**Solution**: Use POSIX character classes instead of backslash escapes:
```jq
# Instead of gsub("^\\s+|\\s+$"; "")
gsub("^[[:space:]]+|[[:space:]]+$"; "")
```
`[[:space:]]` has zero backslashes and passes through all layers safely.

#### Dollar-Sign Risk
jq's `as $variable` bindings contain `$`. While command substitution output
within double quotes is NOT re-expanded for `$`, it is safer and more readable
to use **intermediate object fields** instead (see Pattern 3).

#### Quote Safety
Double-quote characters (`"`) in the jq filter (for string delimiters, string
interpolation) pass through bash `"$(yq ...)"` safely — command substitution
output is never re-parsed for quotes. Use YAML literal block scalar (`|`) for
the filter value.

### 3. Intermediate-Field Pattern

Instead of jq `as $var` bindings (which introduce `$` escaping concerns), build
temporary objects with helper fields, then strip them in the final construction:

```jq
{
  # ... compute derived values as temporary fields ...
  _normalized_roles: (.roles | map(trim_and_lower) | unique),
  _blocked_domains: (.blocked_domains | map(trim_and_lower)),
  email_domain: (.email | split("@")[1] | ascii_downcase)
} |
# Filter using the intermediate fields
select(._normalized_roles | any(. == "admin" or . == "owner")) |
select(.email_domain as $ed | ._blocked_domains | index($ed) | not) |
# Final output: explicitly list only desired fields (temporaries excluded)
{
  user_id: .id,
  username: .username,
  account_summary: {
    role_count: (._normalized_roles | length),
    primary_role: (if (._normalized_roles | length) > 0 then ._normalized_roles[0] else null end),
    roles: ._normalized_roles
  }
}
```

**Key insight**: The `index()` function's argument is evaluated in the context
of the piped array, not the outer object. To reference an outer field inside
`index()`, capture it first with `as $var`:
```jq
select(.email_domain as $ed | ._blocked_domains | index($ed) | not)
```

### 3b. Optional Nested Objects and Deep Field Access

When input records have optional nested structures, use defensive access patterns:

#### Safe Navigation with `//` and `?`
```jq
# Access deeply nested optional field with fallback
.address.city // "Unknown"

# Suppress errors for missing paths
.metadata.tags[0] // null

# Combine: try to access, fallback if missing or error
(.profile.settings.theme // "default")
```

#### Combining Multiple Source Fields into One Output Field
```jq
# Concatenate fields
full_name: "\(.first_name) \(.last_name)"

# Choose first non-null value
primary_contact: (.email // .phone // "N/A")

# Merge multiple fields into structured output
address: {
  street: .street,
  city: .city,
  zip: (.zip | tostring)
}
```

### 4. Value Normalization Patterns

#### Trimming Whitespace
```jq
gsub("^[[:space:]]+|[[:space:]]+$"; "")
```

#### Case Folding
```jq
ascii_downcase   # For ASCII strings (role names, domains)
```

#### Null/Missing Value Handling
```jq
# Use alternative operator for null → default
(.phone // "") | gsub("^[[:space:]]+|[[:space:]]+$"; "") |
if . == "" then "unknown" else . end
```

#### Date Extraction from ISO 8601
```jq
.last_login | split("T")[0]   # "2026-03-16T05:01:40.829540Z" → "2026-03-16"
```

#### Email Domain Extraction
```jq
.email | split("@")[1] | ascii_downcase
```

#### Numeric Coercion
```jq
# Convert string to number
.age_str | tonumber   # "25" → 25

# Convert number to string
.count | tostring     # 42 → "42"

# Safe conversion with fallback
(.score // 0) | tonumber   # null → 0, "85" → 85
```

#### Boolean Derivation
```jq
# Derive boolean from condition
.is_adult: (.age >= 18)

# Derive boolean from array membership
.has_admin: (.roles | any(. == "admin"))

# Derive boolean from null/empty check
.is_active: (.status != null and .status != "")
```

### 5. Collection Operations

#### Deduplication + Sorting in One Step
`unique` in jq both deduplicates AND sorts ascending:
```jq
.roles | map(normalize) | unique
# Returns sorted, deduplicated list
```

#### Membership Testing
```jq
# Check if value exists in array
._blocked_domains | index($value) | not   # true if NOT in list

# Check if any element matches predicate
._normalized_roles | any(. == "admin" or . == "owner")
```

#### Counting
```jq
._normalized_roles | length
```

### 5b. Cross-Record Aggregation (group_by, reduce, collection summaries)

When tasks require aggregating **across multiple records** (not just within one record), use these patterns:

#### Grouping Records with `group_by`
```jq
# Group all records by a field, then aggregate each group
[group_by(.email_domain)[] | 
  {
    domain: .[0].email_domain,
    user_count: length,
    users: [.[] | .username]
  }
]
```
**Key**: `group_by` automatically sorts the input by the grouping key and returns an array of arrays, where each inner array contains all records with the same key value. No pre-sorting is required.

#### Aggregation with `reduce`
```jq
# Sum a field across all records
reduce .[] as $item (0; . + $item.count)

# Build a frequency map
reduce .[] as $item ({}; 
  .[$item.category] = ((.[$item.category] // 0) + 1)
)
```
**Key**: `reduce` takes an initial accumulator value and a function that updates it for each element. Use when you need running totals, maps, or complex aggregation logic.

#### Collection-Level Summaries
```jq
# Compute statistics across the entire dataset
{
  total_records: length,
  average_age: ([.[].age] | add / length),
  max_score: ([.[].score] | max),
  unique_categories: ([.[].category] | unique | length)
}
```
**Key**: Use array comprehensions `[.[].field]` to extract all values of a field, then apply aggregation functions (`add`, `max`, `min`, `unique`, etc.).

#### Combining Per-Record Transformation with Cross-Record Aggregation
```jq
# First transform each record, then aggregate across all transformed records
[.[] | {name, score: (.score * 2)}] |  # Transform
{
  total: ([.[].score] | add),
  records: .  # Keep the transformed array
}
```
**Key**: Chain transformations and aggregations in a single pipeline. Use `[.[] | ...]` to collect transformed records, then apply aggregation functions to the result.

### 6. Artifact Format for Reproducible Pipelines

#### cmd.sh — Direct execution script
Use single quotes around the filter to avoid all shell escaping:
```bash
jq --indent 2 'FILTER_EXPRESSION' input.json > output.json
```

#### jq_args.yaml — Machine-readable argument store
```yaml
filter: |
  [FILTER_EXPRESSION]
args:
  - "--indent 2"
```

**Reconstruction command**:
```bash
jq $(yq -r '.args[]' jq_args.yaml) "$(yq -r '.filter' jq_args.yaml)" input.json > output.json
```

**Verification step** — always confirm both paths produce identical output:
```bash
diff direct_output.json reconstructed_output.json
```

## Pipeline Architecture Template

A typical jq data-processing pipeline follows this structure:

```
[.[] |                          # Iterate over input array
  select(GUARD_CONDITIONS) |    # Filter records (status, type, etc.)
  {                             # Build intermediate object
    # ... direct field mappings ...
    # ... normalized/derived fields ...
    _temp1: (COMPUTATION_1),    # Temporary helper fields (prefixed with _)
    _temp2: (COMPUTATION_2)
  } |
  select(TEMPORAL_FILTERS) |    # Filters that depend on computed values
  {                             # Final output construction
    # Explicitly list only desired output fields
    # Temporary fields are excluded by omission
  }
] |
sort_by(SECONDARY_KEY) | reverse |  # Mixed-direction sort chain
sort_by(PRIMARY_KEY)                # (least significant → most significant)
```

## Common Pitfalls

1. **Context loss after pipe**: After `|`, `.` refers to the piped value, not
   the outer object. Capture outer fields with `as $var` before piping.

2. **`unique` vs `group_by`**: `unique` deduplicates and sorts. Use `group_by`
   when you need to aggregate over groups.

3. **`//` operator precedence**: `(.phone // "")` needs parentheses when used
   in a pipeline.

4. **String interpolation in YAML**: Use literal block scalar (`|`) to avoid
   YAML interpreting backslashes or special characters in the filter.

5. **`index` returns null for missing**: `array | index(value)` returns `null`
   when value is not found. Use `| not` or `== null` to test absence.

6. **Sorting after array collection**: `sort_by` operates on arrays. Collect
   records into an array with `[... | ...]` before sorting.
