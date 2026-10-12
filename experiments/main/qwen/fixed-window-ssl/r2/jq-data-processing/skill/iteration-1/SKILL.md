---
name: jq-data-processing
description: >
  Build jq pipelines that filter, normalize, reshape, aggregate, and sort JSON
  record arrays into structured output files. Covers multi-condition selection,
  string/value normalization, field derivation and nesting, per-record and
  cross-record aggregation, and multi-key mixed-direction sorting.
---

# jq Data Processing Skill

## Overview

This skill covers building `jq` pipelines that transform JSON arrays of records
into filtered, normalized, reshaped, and sorted output. The canonical workflow
is: **normalize → filter → shape → collect → sort → output**.

## Pipeline Architecture

The standard pipeline structure is:

```jq
[
  .[] |
  # 1. Compute normalized values as local variables
  # 2. Filter with select()
  # 3. Shape the output record
]
# 4. Sort the collected array
| sort_by(...)
```

### Step 1: Normalize Early

Compute all normalized values as `as $var` bindings at the top of each record's
processing. This avoids repeating normalization logic and keeps filters clean.

```jq
.[] |
  (.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $norm_roles |
  (.email | split("@")[1] | ascii_downcase) as $domain |
  (.blocked_domains | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $blocked |
  ...
```

**Key normalization patterns:**
- **Trim whitespace**: `gsub("^\\s+|\\s+$"; "")` — works on any string field
- **Lowercase**: `ascii_downcase` — for case-insensitive comparisons
- **Deduplicate + sort**: `unique` — sorts ascending and removes duplicates
- **Null coalescing**: `(.field // "")` — replaces null with empty string
- **Extract substring**: `.field[0:10]` — e.g., ISO 8601 date → YYYY-MM-DD
- **Split and extract**: `.field | split("@")[1]` — extract domain from email

### Step 2: Filter with select()

Combine multiple conditions with `and`/`or` inside `select()`:

```jq
select(
  .status == "active"
  and ($norm_roles | any(. == "admin" or . == "owner"))
  and (IN($domain; $blocked[]) | not)
)
```

**Selection patterns:**
- **Equality**: `.field == "value"`
- **Membership in set**: `.field | any(. == "a" or . == "b")`
- **Value in array**: `IN($value; $array[])` — tests if $value equals any element
- **Negation**: `... | not`
- **Multi-field predicates**: combine with `and`/`or`
- **Derived value checks**: compute a value first, then filter on it

### Step 3: Shape Output Records

Build the output object with renamed fields, derived fields, and nested objects:

```jq
{
  user_id: .id,                          # rename
  username: .username,                    # pass-through
  email_domain: $domain,                 # from normalized variable
  contact: "\(.username) <\(.email)>",   # string interpolation
  phone: $phone,                         # from conditional logic
  last_login: .last_login[0:10],         # substring extraction
  account_summary: {                     # nested object
    role_count: ($unique_roles | length),
    primary_role: (if ... then ... else ... end),
    roles: $unique_roles
  }
}
```

**Reshaping patterns:**
- **Rename fields**: `new_name: .old_field`
- **String interpolation**: `"\(.field1) text \(.field2)"`
- **Nested output objects**: `{ nested: { ... } }`
- **Conditional values**: `if condition then value1 else value2 end`
- **Fallback defaults**: `if (.field | length) == 0 then "default" else .field end`
- **Null propagation**: use `null` explicitly when no value exists

### Step 4: Sort the Collected Array

After collecting into an array with `[...]`, apply sorting.

#### Ascending sort (single or multi-key):
```jq
| sort_by(.field1, .field2)
```

#### Mixed-direction sort (ascending + descending):

`sort_by` only does ascending. For descending string sorts, use the
**group-then-reverse** pattern:

```jq
| sort_by(.ascending_key, .descending_key)  # both ascending first
| group_by(.ascending_key)                   # group by the ascending key
| map(reverse)                               # reverse within each group
| add // []                                  # flatten back; // [] guards empty input
```

**Why this works:**
1. `sort_by(.a, .b)` orders by `a` ascending, then `b` ascending within same `a`
2. `group_by(.a)` splits into groups sharing the same `a` value
3. `reverse` within each group flips `b` to descending order
4. `add` concatenates groups back (groups remain in ascending `a` order)

## Value Normalization Details

### String Cleanup
```jq
# Trim surrounding whitespace
gsub("^\\s+|\\s+$"; "")

# Lowercase
ascii_downcase

# Combined: trim then lowercase
gsub("^\\s+|\\s+$"; "") | ascii_downcase
```

### Null and Missing Values
```jq
# Null coalescing: use default when field is null
(.phone // "") | gsub("^\\s+|\\s+$"; "")

# Blank-or-null detection: trim then check length
((.field // "") | gsub("^\\s+|\\s+$"; "")) as $trimmed |
if ($trimmed | length) == 0 then "default_value" else $trimmed end
```

### Date Extraction
```jq
# ISO 8601 → YYYY-MM-DD via string slicing
.last_login[0:10]
```

### Numeric Coercion
```jq
# String to number
.field | tonumber

# Number to string
.field | tostring
```

## Aggregation and Collection Operations

### Per-Record Aggregation
```jq
# Count unique values
($norm_values | unique | length) as $count

# First from sorted list (or null)
(if ($sorted | length) == 0 then null else $sorted[0] end) as $first
```

### Cross-Record Aggregation
```jq
# Group by a field and aggregate
group_by(.category) | map({
  key: .[0].category,
  count: length,
  items: [.[].name]
})

# Flatten nested arrays
[.[] | .nested_array[]] | unique

# Collection-level summary
{
  total: length,
  avg: (map(.value) | add / length)
}
```

## Output Formatting

### jq Flags
- `--indent 2` — 2-space indentation (jq 1.6+)
- `-r` — raw output (for strings without quotes)
- `-c` — compact output (single line)
- `-S` — sort object keys

### Artifact Structure
Typical deliverables:
1. **Output JSON file**: the transformed data
2. **cmd.sh**: the exact shell command executed (including redirection)
3. **jq_args.yaml**: structured args with `filter` (string) and `args` (list of strings)

The reconstruction pattern:
```bash
jq $(yq -r '.args[]' jq_args.yaml) "$(yq -r '.filter' jq_args.yaml)" input.json > output.json
```

## Common Pitfalls

1. **Sorting inside iteration**: `sort_by` must operate on the collected array, not inside `.[]`. Always collect first with `[...]`, then sort.

2. **Forgetting to normalize before comparison**: Always normalize both sides of a comparison (e.g., trim+lowercase roles before checking if "admin" is present).

3. **Null phone values**: Use `(.phone // "")` to handle null, then trim, then check if empty for default value.

4. **Blocked-domain logic**: Normalize both the email domain and each blocked domain entry before comparison. Use `IN()` for clean membership testing.

5. **Descending sort for strings**: Cannot negate strings. Must use group-then-reverse pattern.

6. **`unique` already sorts**: jq's `unique` returns sorted, deduplicated array. Use this for "sorted unique roles" directly.

7. **String interpolation in jq**: Use `\(.field)` inside double-quoted strings: `"\(.username) <\(.email)>"`.

8. **`add` on empty array returns `null`**: After `group_by(...) | map(reverse) | add`, if the input array was empty, `add` produces `null` instead of `[]`. Always use `add // []` to ensure the output remains a JSON array when no records match the filters.

## Generalization Checklist

When facing a new variant of this task family:

- [ ] Identify all fields that need normalization (trim, lowercase, etc.)
- [ ] Determine selection criteria (status, role membership, exclusion lists)
- [ ] Map input fields to output fields (renames, derivations, combinations)
- [ ] Identify aggregation needs (counts, first/last, grouped summaries)
- [ ] Determine sort keys and directions (ascending/descending per key)
- [ ] Handle edge cases: null values, blank strings, empty arrays
- [ ] Choose appropriate jq flags for output formatting
- [ ] Structure pipeline: normalize → filter → shape → collect → sort
