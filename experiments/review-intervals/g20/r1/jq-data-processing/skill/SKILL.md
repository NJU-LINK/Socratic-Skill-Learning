---
name: jq-data-processing
description: Transform JSON data using jq pipelines with filtering, normalization, reshaping, aggregation, and multi-key sorting. Handles complex predicates, nested field access, value coercion, and cross-record operations.
---

# jq Data Processing Skill

This skill enables transformation of JSON arrays into filtered, normalized, reshaped, and sorted output using jq pipelines. It applies to tasks requiring complex selection logic, field derivation, value normalization, and aggregation operations.

## Solving Workflow

1. **Read task spec** — identify required filters, output schema, sort order, normalization rules
2. **Inspect input** — check structure, field names, data types, edge cases (nulls, whitespace, casing)
3. **Build jq filter** — follow pipeline architecture below, using `as` bindings for normalized values
4. **Create output files** — `jq_args.yaml` (literal block scalar filter + args list), `cmd.sh`, output JSON
5. **Verify reconstruction** — run `jq $(yq -r '.args[]' ...) "$(yq -r '.filter' ...)" input > /tmp/verify.json` and diff
6. **Validate args format** — every item in args list must start with `-` (flag+value combined)
7. **Test edge cases** — check null handling, empty arrays, blocked-domain exclusion, sort order

## Pipeline Architecture

Standard decomposition into composable stages:

1. **Normalize** - Clean and standardize input values (trim whitespace, lowercase, extract parts)
2. **Filter** - Apply inclusion/exclusion predicates using `select()`
3. **Transform** - Reshape records, derive new fields, combine source fields
4. **Aggregate** - Count, group, deduplicate, compute summaries
5. **Sort** - Order output by one or more keys with mixed directions
6. **Format** - Apply indentation, structure output as array/object

Each stage should be independent and testable. Use `as` bindings to capture intermediate normalized values before filtering or transformation.

## Value Normalization Patterns

### Trim and lowercase
```jq
gsub("^\\s+|\\s+$";"") | ascii_downcase
```
Apply to role names, domain names, enum values, or any field requiring case-insensitive comparison.

### Extract email domain
```jq
.email | split("@")[1] | ascii_downcase
```

### Date extraction from ISO 8601
```jq
.last_login | split("T")[0]
```
Extracts YYYY-MM-DD portion.

### Null/blank handling with fallback
```jq
if .phone == null or (.phone | gsub("^\\s+|\\s+$";"") | length) == 0 
then "unknown" 
else (.phone | gsub("^\\s+|\\s+$";"")) 
end
```
Check both `null` and empty-after-trim conditions. Use `// []` for array fields that might be missing.

### Array normalization
```jq
.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase)
```
Normalize each element before deduplication or filtering.

## Multi-Condition Filtering

### Combining predicates
```jq
select(.status == "active" and $has_priv and ($blocked | index($email_domain) | not))
```

### Pattern: normalize before filter
```jq
(.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique) as $norm_roles |
($norm_roles | any(. == "admin" or . == "owner")) as $has_priv |
(.email | split("@")[1] | ascii_downcase) as $email_domain |
(.blocked_domains // [] | map(gsub("^\\s+|\\s+$";"") | ascii_downcase)) as $blocked |
select(.status == "active" and $has_priv and ($blocked | index($email_domain) | not))
```

**Key insight**: Use `as` bindings to compute normalized values once, then reference them in `select()`. This avoids redundant computation and makes logic clearer.

### Inclusion logic
- Check membership: `array | index(value)` returns index or `null`
- Check if any element matches: `array | any(. == "value")`
- Check if array contains value: `array | contains(["value"])`

### Exclusion logic
- Invert membership test: `array | index(value) | not`
- Exclude if in blocked list: `($blocked | index($domain) | not)`

**Pitfall**: `index()` returns `null` (not `false`) when item not found. Use `| not` to convert to boolean.

## Field Derivation and Reshaping

### Rename fields
```jq
{ user_id: .id, username: .username }
```

### Combine fields into one
```jq
contact: "\(.username) <\(.email)>"
```

### Extract from nested context
```jq
email_domain: (.email | split("@")[1] | ascii_downcase)
```

### Build nested output objects
```jq
account_summary: {
  role_count: ($norm_roles | length),
  primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
  roles: $norm_roles
}
```

### Handle optional nested objects
Use `// default` operator:
```jq
.blocked_domains // []
```

## Aggregation and Collection Operations

### Deduplicate and sort
```jq
.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique
```
`unique` both deduplicates AND sorts the result.

### Count elements
```jq
$norm_roles | length
```

### First element with null guard
```jq
if ($norm_roles | length) > 0 then $norm_roles[0] else null end
```

### Group by field
```jq
group_by(.email_domain)
```
Returns array of arrays, grouped by field value.

### Flatten grouped arrays
```jq
group_by(.field) | map(...) | add
```
`add` concatenates arrays.

## Mixed-Direction Sorting

### Ascending by field1, descending by field2
```jq
group_by(.email_domain) | map(sort_by(.username) | reverse) | add // []
```

**Pattern**: 
1. `group_by(.field1)` - groups by first sort key (ascending order)
2. `map(sort_by(.field2) | reverse)` - within each group, sort by second key descending
3. `add // []` - flatten back to single array; `// []` guards against empty input (since `add` on `[]` returns `null`)

**Alternative for multiple ascending keys**:
```jq
sort_by(.field1, .field2)
```

**Pitfall**: `sort_by` only sorts ascending. For mixed directions, use the group_by/reverse pattern.

## Shell and YAML Integration

### YAML literal block scalar for jq filters
```yaml
filter: |
  [
    .[] |
    (.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique) as $norm_roles |
    ...
  ]
```

**Why**: In literal block scalars (`|`), backslashes are literal. No YAML escaping needed for `\\s` or `\\( )`. This is critical for jq filters containing regex and string interpolation.

### Args list structure

**Critical constraint**: Each item in the args list must be a **complete jq argument including both flag and value**. Tests verify that every item starts with `-`.

**Correct format**:
```yaml
args:
  - "--indent 2"
```

**Incorrect format** (will fail validation):
```yaml
args:
  - "--indent"
  - "2"  # ERROR: doesn't start with -
```

Shell expansion `$(yq -r '.args[]')` produces separate words, so `"--indent 2"` becomes two shell arguments as jq expects.

### Parameterizing filters with --arg and --argjson

Extract parameterizable values from the task spec and pass them via flags rather than embedding literals in the filter. This makes filters modular and reduces YAML escaping complexity.

**--arg name value** — passes `value` as a jq **string** variable `$name`:
```bash
jq --arg status "active" '.[] | select(.status == $status)' input.json
```

**--argjson name value** — parses `value` as **JSON** and binds it to `$name` (use for arrays, numbers, booleans):
```bash
jq --argjson priv_roles '["admin","owner"]' '.[] | select(.roles | any(. as $r | $priv_roles | index($r)))' input.json
```

In YAML args list (each item must start with `-`):
```yaml
args:
  - "--indent 2"
  - "--arg status active"
  - "--argjson priv_roles [\"admin\",\"owner\"]"
```

**When to parameterize**: Status values, role sets, thresholds, field names that vary across family members. Keep structural logic (normalization patterns, filtering composition) in the filter.

### Verification via reconstruction
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > /tmp/verify.json
diff /app/output.json /tmp/verify.json
```
This catches YAML escaping bugs that produce wrong output or parse errors.

## Common Pitfalls

### Phone null/blank handling
Check both conditions:
```jq
if .phone == null or (.phone | gsub("^\\s+|\\s+$";"") | length) == 0
```

### `unique` vs `unique_by`
- `unique` - deduplicates entire values
- `unique_by(.field)` - deduplicates by field value

### `sort_by` with array keys
```jq
sort_by([.field1, .field2])
```
Sorts by field1, then field2 for ties. Both ascending.

### `index()` returns null, not false
```jq
array | index(value) | not  # converts null to true, index to false
```

### Empty array edge cases
- `unique` on empty array returns `[]`
- `.[0]` on empty array returns `null`
- `length` on empty array returns `0`
- **`add` on empty array returns `null`, not `[]`** — guard with `// []` if empty input is possible:
  ```jq
  group_by(.field) | map(...) | add // []
  ```
- Guard first-element access: `if (array | length) > 0 then array[0] else null end`

### String interpolation in YAML
In literal block scalars, `\(.field)` is stored verbatim. In double-quoted strings, must escape as `\\(.field)`.

## Debugging Techniques

### Check intermediate values
```jq
.[] | {
  original: .roles,
  normalized: (.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase)),
  unique: (.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique)
}
```

### Count records at each stage
```bash
jq 'length' input.json  # before
jq '[.[] | select(...)] | length' input.json  # after filter
```

### Verify specific records
```jq
jq '.[] | select(.id == 42)' output.json
```

## Example: Complete Pipeline

```jq
[
  .[] |
  # Normalize roles
  (.roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase) | unique) as $norm_roles |
  
  # Check privileged
  ($norm_roles | any(. == "admin" or . == "owner")) as $has_priv |
  
  # Extract and normalize domain
  (.email | split("@")[1] | ascii_downcase) as $email_domain |
  
  # Normalize blocked domains
  (.blocked_domains // [] | map(gsub("^\\s+|\\s+$";"") | ascii_downcase)) as $blocked |
  
  # Filter
  select(.status == "active" and $has_priv and ($blocked | index($email_domain) | not)) |
  
  # Transform
  {
    user_id: .id,
    username: .username,
    email: .email,
    email_domain: $email_domain,
    contact: "\(.username) <\(.email)>",
    phone: (if .phone == null or (.phone | gsub("^\\s+|\\s+$";"") | length) == 0 
            then "unknown" 
            else (.phone | gsub("^\\s+|\\s+$";"")) end),
    last_login: (.last_login | split("T")[0]),
    account_summary: {
      role_count: ($norm_roles | length),
      primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
      roles: $norm_roles
    }
  }
] | group_by(.email_domain) | map(sort_by(.username) | reverse) | add // []
```

This pattern generalizes to any task requiring:
- Multi-condition filtering with normalized values
- Field renaming and derivation
- Value normalization (trim, lowercase, extract)
- Aggregation (count, deduplicate, first-element)
- Mixed-direction sorting
- Null/blank handling with fallbacks

## Robustness Against Adversarial Inputs

Filters may be replayed against modified inputs with edge cases. Ensure:

### Null-safe field access
```jq
.blocked_domains // []  # missing field becomes empty array
.phone // null          # missing field becomes null
```

### Both null AND empty-string checks
```jq
if .phone == null or (.phone | gsub("^\\s+|\\s+$";"") | length) == 0
then "unknown"
else (.phone | gsub("^\\s+|\\s+$";""))
end
```

### Whitespace and case normalization
Always trim + lowercase before comparison:
```jq
gsub("^\\s+|\\s+$";"") | ascii_downcase
```

### Empty array guards
```jq
# add on empty array returns null, not []
group_by(.field) | map(...) | add // []

# Guard first-element access
if (array | length) > 0 then array[0] else null end
```

### Defensive filtering
Use `// []` for array fields that might be missing, `any()` for membership checks that should return false on empty arrays.

## Pre-Submission Verification Checklist

Before declaring the task complete, verify:

- [ ] Output file exists and is valid JSON
- [ ] Record count matches expected (check filtering logic)
- [ ] All required fields present in output schema
- [ ] Field types correct (numbers, strings, arrays, objects)
- [ ] Normalization applied (trim, lowercase, date extraction)
- [ ] Fallback defaults working (null/blank → "unknown")
- [ ] Exclusion logic correct (blocked domains, inactive status)
- [ ] Sort order correct (check first/last in each group)
- [ ] Args format valid (each item starts with `-`)
- [ ] Reconstruction command produces identical output
- [ ] cmd.sh is executable and produces correct output
- [ ] Indentation matches spec (e.g., 2 spaces)

## Common Validation Constraints

### Args list format
Each item must be a complete jq argument (flag + value combined):
```yaml
args:
  - "--indent 2"      # ✓ correct
  - "--indent"        # ✗ wrong (value separate)
  - "2"               # ✗ wrong (doesn't start with -)
```

### YAML filter escaping
Use literal block scalar (`|`) for jq filters to avoid backslash escaping:
```yaml
filter: |
  .roles | map(gsub("^\\s+|\\s+$";"") | ascii_downcase)
```

### Reconstruction command
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > /app/output.json
```
Must produce output identical to direct execution.
