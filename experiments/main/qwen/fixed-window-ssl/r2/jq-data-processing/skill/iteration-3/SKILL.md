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
  ((.roles // []) | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $norm_roles |
  ((.email // "") | split("@") | if length > 1 then .[1] else "" end | ascii_downcase) as $domain |
  ((.blocked_domains // []) | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $blocked |
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
  (.status // "") == "active"
  and ($norm_roles | any(. == "admin" or . == "owner"))
  and (IN($domain; $blocked[]) | not)
)
```

**Selection patterns:**
- **Equality**: `.field == "value"`
- **Inequality**: `.field != "value"`
- **Membership in set**: `.field | any(. == "a" or . == "b")`
- **Value in array**: `IN($value; $array[])` — tests if $value equals any element
- **Negation**: `... | not`
- **Multi-field predicates**: combine with `and`/`or`
- **Derived value checks**: compute a value first, then filter on it
- **Range checks**: `.age >= 18 and .age < 65`
- **Pattern matching**: `.email | test("@company\\.com$")`
- **Null checks**: `.field != null`, `.field | type == "null"`
- **Array length checks**: `(.items | length) > 0`
- **String emptiness**: `(.name | length) > 0`

**Complex selection examples:**
```jq
# Multiple conditions with derived values
select(
  (.status // "") == "active"
  and (.roles | map(ascii_downcase) | any(. == "admin"))
  and (.email | test("@company\\.com$"))
  and ((.blocked_domains // []) | map(ascii_downcase) | IN(.email_domain; .[]) | not)
)

# Exclude based on computed field
(.score / .max_score) as $ratio |
select($ratio >= 0.5)
```

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
- **Deep field access**: `.address.city` or `.metadata.tags[0]`
- **Optional nested objects**: `(.profile // {}) | .bio`
- **Combining multiple source fields**: `{full_name: "\(.first) \(.last)"}`
- **Array output fields**: `{tags: [.categories[], .labels[]] | unique}`
- **Conditional field inclusion**: use `if` to include/exclude fields based on conditions

### Step 4: Sort the Collected Array

After collecting into an array with `[...]`, apply sorting.

#### Ascending sort (single or multi-key):
```jq
| sort_by(.field1, .field2)
```

#### Descending sort (single key):
```jq
| sort_by(.field) | reverse
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

#### Sorting by derived values:
```jq
# Sort by computed field
| sort_by(.first_name + " " + .last_name)

# Sort by array length
| sort_by(.tags | length)

# Sort by nested field
| sort_by(.address.city)

# Sort by multiple keys with different directions
| sort_by(.department, -.salary)  # department asc, salary desc (numeric only)
```

#### Complex multi-key sorting:
```jq
# Three-level sort: region asc, department asc, name desc
| sort_by(.region, .department, .name)
| group_by(.region, .department)
| map(reverse)
| add // []
```

## Value Normalization Details

### String Cleanup
```jq
# Trim surrounding whitespace
gsub("^\\s+|\\s+$"; "")

# Lowercase
ascii_downcase

# Uppercase
ascii_upcase

# Combined: trim then lowercase
gsub("^\\s+|\\s+$"; "") | ascii_downcase

# Remove all whitespace
gsub("\\s+"; "")

# Replace specific characters
gsub("[^a-zA-Z0-9]"; "_")
```

### Extracting Parts of Structured Strings
```jq
# Extract domain from email
.email | split("@")[1]

# Extract file extension
.filename | split(".")[-1]

# Extract year from date string (YYYY-MM-DD)
.date[0:4]

# Extract parts with regex
capture("^(?<area>\\d{3})-(?<prefix>\\d{3})-(?<line>\\d{4})$") | .area

# Split and take specific parts
.phone | split("-") | .[0]  # area code
```

### Boolean Derivation
```jq
# Check if array contains value
(.roles | any(. == "admin")) as $is_admin

# Check if string matches pattern
(.email | test("@company\\.com$")) as $is_company_email

# Check if number is in range
(.age >= 18 and .age < 65) as $is_working_age

# Check if field exists and is non-empty
(.field != null and .field != "") as $has_value
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

# Last from sorted list
(if ($sorted | length) == 0 then null else $sorted[-1] end) as $last

# Sum/average of numeric array
($values | add) as $sum
($values | add / length) as $avg

# Join array into string
($items | join(", ")) as $csv
```

### Cross-Record Aggregation

**Group by a field and aggregate:**
```jq
group_by(.category) | map({
  key: .[0].category,
  count: length,
  items: [.[].name],
  total_value: (map(.value) | add)
})
```

**Flatten nested arrays:**
```jq
# Extract all items from nested arrays across records
[.[] | .tags[]] | unique

# Flatten array of arrays
[.[] | .nested_array[]] | sort
```

**Deduplication patterns:**
```jq
# Unique by a specific field (keep first occurrence)
group_by(.email) | map(.[0])

# Unique values across all records
[.[] | .role] | unique

# Count occurrences of each value
group_by(.status) | map({status: .[0].status, count: length})
```

**Collection-level summaries:**
```jq
{
  total: length,
  avg_value: (map(.value) | add / length),
  min_value: ([.[].value] | min),
  max_value: ([.[].value] | max),
  categories: ([.[].category] | unique)
}
```

**Combining per-record transformation with cross-record aggregation:**
```jq
# Example: Transform each record, then group and summarize
[
  .[] |
  # Per-record transformation
  (.name | ascii_downcase) as $norm_name |
  {
    name: $norm_name,
    department: .dept,
    salary: .pay
  }
]
| group_by(.department)
| map({
    department: .[0].department,
    employees: [.[].name],
    headcount: length,
    total_salary: (map(.salary) | add),
    avg_salary: (map(.salary) | add / length)
  })
| sort_by(.department)
```

**Multi-level grouping:**
```jq
# Group by two fields
group_by(.region, .category) | map({
  region: .[0].region,
  category: .[0].category,
  count: length,
  items: [.[].name]
})
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

## Defensive Programming for Adversarial Inputs

Real-world JSON data often has missing or null fields. Use the `//` (alternative) operator to provide defaults before iterating or transforming:

### Mandatory Guards Before Iteration

**Array fields** that might be null/missing — use `// []` before `map`, `any`, `IN`, or `unique`:
```jq
# Without guard: crashes if .roles is null
.roles | map(...)  # ERROR: Cannot iterate over null

# With guard: safe
((.roles // []) | map(...)) as $norm_roles
((.blocked_domains // []) | map(...)) as $blocked
```

**String fields** that might be null — use `// ""` before `gsub`, `split`, or string operations:
```jq
# Without guard: crashes if .phone is null
.phone | gsub(...)  # ERROR: Cannot index a null value

# With guard: safe
((.phone // "") | gsub(...)) as $trimmed
((.email // "") | split("@")) as $parts
```

### IN() on Empty Streams is Already Correct

`IN($value; $array[])` on an empty array produces `false` (the empty stream has no matches), so `| not` gives `true` — correctly including the record. No special case needed:

```jq
# All these work correctly without special handling:
# $blocked = [] → IN() = false → | not = true → included ✓
# $blocked = ["x"], domain = "x" → IN() = true → | not = false → excluded ✓
# $blocked = ["x"], domain = "y" → IN() = false → | not = true → included ✓
```

### Operator Precedence with and/or

When combining `and` and `or`, **always use explicit parentheses**. jq's precedence can be surprising:

```jq
# WRONG: parses as (A and B) or C
select(.status == "active" and ($roles | any(. == "admin")) or .verified == true)

# CORRECT: explicit grouping
select((.status == "active") and (($roles | any(. == "admin")) or (.verified == true)))
```

### Email Domain Extraction with Missing @

When extracting domains from emails that might lack `@`:
```jq
# Safe extraction: returns "" if no @ present
((.email // "") | split("@") | if length > 1 then .[1] else "" end | ascii_downcase) as $domain
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

9. **Missing field guards**: Always use `// []` for array fields and `// ""` for string fields before iterating or transforming. This prevents "Cannot iterate over null" errors on adversarial inputs.

10. **Operator precedence in filters**: When combining `and` and `or` in `select()`, use explicit parentheses to avoid unexpected behavior.

## Generalization Checklist

When facing a new variant of this task family:

- [ ] Identify all fields that need normalization (trim, lowercase, etc.)
- [ ] Determine selection criteria (status, role membership, exclusion lists)
- [ ] Map input fields to output fields (renames, derivations, combinations)
- [ ] Identify aggregation needs (counts, first/last, grouped summaries)
- [ ] Determine sort keys and directions (ascending/descending per key)
- [ ] Handle edge cases: null values, blank strings, empty arrays
- [ ] Add defensive guards (`// []` for arrays, `// ""` for strings) before any iteration or string operation
- [ ] Choose appropriate jq flags for output formatting
- [ ] Structure pipeline: normalize → filter → shape → collect → sort
