---
name: jq-data-processing
description: >
  Build complex jq-based JSON transformation pipelines that combine multi-condition
  selection, field reshaping, value normalization, and per-record or cross-record
  aggregation. Covers the full workflow from incremental development on small slices
  through final output formatting and artifact storage.
---

# jq Data Processing Skill

Transform JSON arrays into reshaped, filtered, normalized, and sorted reports using `jq`. This skill covers the decision framework for building pipelines across four axes: selection/ordering, field derivation, value normalization, and aggregation.

## General Strategy: Build Incrementally

Never compose a monolithic filter from scratch. Instead:

1. **Slice first**: test each stage on `.[0:5]` or `.[0:3]` before running on the full dataset.
2. **Name intermediate values** with `as $var` bindings — this makes filters readable and debuggable.
3. **Verify counts** at each filtering stage to confirm the right records survive.
4. **Check edge cases** explicitly: null fields, empty arrays, whitespace-only strings.
5. **Compose last**: only merge stages once each one is independently verified.

## Axis 1: Selection and Ordering Logic

### Multi-condition filtering

Chain `select()` calls sequentially — each one narrows the stream:

```jq
.[] |
  select(.status == "active") |
  select(.roles | any(. == "admin" or . == "owner")) |
  select(.blocked_domains | index(.email_domain) | not)
```

For predicates that depend on computed values, bind first then select:

```jq
(.roles | map(normalize) | unique) as $norm_roles |
select($norm_roles | any(. == "admin" or . == "owner"))
```

### Mixed-direction sorting

`sort_by` only sorts ascending. For multi-key sort with mixed directions:

**Group-then-reverse** (preferred — clear, correct, handles all types):

```jq
sort_by(.primary_key) |
group_by(.primary_key) |
map(sort_by(.secondary_key) | reverse) |
add // []
```

The `// []` handles the empty-input edge case (since `add` on `[]` returns `null`).

**Character-inversion trick** (compact but fragile — only works for string keys):

```jq
sort_by([.primary_key, (.secondary_key | explode | map(255 - .) | implode)])
```

Use group-then-reverse unless the dataset is very large and the keys are guaranteed to be strings.

### Sorting by derived values

Compute the sort key before sorting, or compute it inline:

```jq
map(. + {email_domain: (.email | split("@")[1] | ascii_downcase)}) |
sort_by(.email_domain)
```

## Axis 2: Field Derivation and Reshaping

### Field renaming

```jq
{user_id: .id, username: .username}
```

### Computed/combined fields

Use string interpolation for combining fields:

```jq
contact: "\(.username) <\(.email)>"
```

### Nested output objects

```jq
account_summary: {
  role_count: ($norm_roles | length),
  primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
  roles: $norm_roles
}
```

### The `as $var` pattern for reuse

Compute expensive or complex values once, then reference them multiple times in the output object:

```jq
(.email | split("@")[1] | ascii_downcase) as $email_domain |
(.roles | map(normalize) | unique) as $norm_roles |
{
  email_domain: $email_domain,
  account_summary: {
    role_count: ($norm_roles | length),
    primary_role: $norm_roles[0],
    roles: $norm_roles
  }
}
```

### Flattening nested arrays into output

When input has arrays and you need to extract/transform elements:

```jq
[.items[] | {name: .name, tags: [.tags[] | ascii_downcase]}]
```

### Deeper field access and optional nested objects

When input has nested structures that may be missing:

```jq
# Safe access to nested fields
.address.city              # errors if .address is null
.address?.city             # returns null if .address is missing
(.address // {}).city      # returns null if .address is missing

# Extract from optional nested array
(.metadata.tags // []) | map(ascii_downcase)

# Flatten nested object into output
{
  user_id: .id,
  city: .address.city,
  country: .address.country,
  # Combine nested fields
  full_address: "\(.address.street), \(.address.city)"
}
```

### Combining multiple source fields

Beyond simple string interpolation:

```jq
# Numeric combination
{total: (.price + .tax + .shipping)}

# Conditional combination
{display_name: (if .nickname then .nickname else .username end)}

# Array aggregation into single field
{all_tags: ([.tags[], .metadata.tags[]?] | unique | join(", "))}
```

## Axis 3: Value Normalization

### String trimming (jq has no `trim()`)

Use regex substitution:

```jq
gsub("^\\s+|\\s+$"; "")
```

This handles leading and trailing whitespace including tabs and newlines.

### Null-safe processing

Always coerce nulls before applying string operations:

```jq
((.phone // "") | gsub("^\\s+|\\s+$"; "") | if . == "" then "unknown" else . end)
```

Pattern: `(.field // "")` converts null to empty string, then normalize, then check for empty.

For arrays that might be null:

```jq
((.blocked_domains // []) | map(normalize))
```

### Case normalization

```jq
ascii_downcase
```

### Date extraction from ISO 8601

The date portion is always the first 10 characters:

```jq
.last_login[0:10]   # "2026-03-16T05:01:40.829540Z" → "2026-03-16"
```

For more complex date parsing, use `split("T")[0]` or regex capture.

### Numeric coercion

```jq
tonumber          # string → number
tostring          # number → string
```

### Boolean derivation

```jq
(.score > 80)     # produces true/false
(if .field then true else false end)
```

### String cleanup and structured extraction

```jq
# Remove specific characters
"phone: (555) 123-4567" | gsub("[^0-9]"; "")    # "5551234567"

# Extract structured parts with regex
"2026-03-16T05:01:40Z" | split("T")[0]          # "2026-03-16"
"user@example.com" | split("@")[0]              # "user"

# Extract with capture (named groups)
"ID: 12345, Name: John" | capture("ID: (?<id>\\d+)") | .id

# Normalize formats (e.g., phone numbers)
"+1-555-123-4567" | gsub("[^0-9+]"; "")

# Extract file extension
"document.pdf" | split(".")[-1]

# Slug generation
"Hello World!" | ascii_downcase | gsub("[^a-z0-9]+"; "-") | gsub("^-|-$"; "")
```

### Fallback defaults and null propagation

```jq
# Chain of fallbacks
(.primary_email // .secondary_email // "no-email@example.com")

# Default for missing nested field
(.config.timeout // 30)

# Null propagation (keep null if source is null)
.field | if . == null then null else (. | normalize) end

# Conditional default based on type
.value | if type == "string" then . else (. | tostring) end
```

## Axis 4: Aggregation and Collection Operations

### Deduplication + sorting in one step

`unique` both deduplicates AND sorts ascending:

```jq
[.roles[] | normalize] | unique
```

### Per-record aggregation

Compute summary fields within each record's transformation:

```jq
{
  role_count: ($norm_roles | length),
  primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
  roles: $norm_roles
}
```

### Cross-record aggregation

Group then aggregate:

```jq
group_by(.category) |
map({
  category: .[0].category,
  count: length,
  items: [.[] | {name, value}]
})
```

### Cross-record statistics

Compute collection-level summaries:

```jq
# Sum across records
[.[] | .price] | add          # total of all prices

# Average
[.[] | .score] | (add / length)   # mean score

# Min/max by a field
[.[] | .age] | min             # youngest
sort_by(.revenue) | last       # highest revenue record

# Count by condition
[.[] | select(.status == "active")] | length
```

### Combining per-record + cross-record in one pipeline

Transform each record, then compute collection-level summary:

```jq
[.[] | {name, total: (.price * .qty)}] |
{
  items: .,
  grand_total: ([.[].total] | add),
  avg_total: ([.[].total] | add / length)
}
```

### Reduce for complex accumulations

Track running state across records:

```jq
# Running total / complex state tracking
reduce .[] as $item (
  {sum: 0, count: 0};
  .sum += $item.value | .count += 1
) | {total: .sum, avg: (.sum / .count)}
```

### Deduplicating values across records

Collect unique values from all records:

```jq
[.[] | .tags[]] | unique    # all unique tags across all records
```

### Membership testing

```jq
# Check if any element matches
$roles | any(. == "admin" or . == "owner")

# Check if value is in a list
$value | IN("admin", "owner")   # jq 1.6+

# Check if value exists in array
$array | index($value) != null
```

### Flattening and rebuilding arrays

```jq
[.[][] ]           # flatten one level
[.[] | .items[]]   # extract all items from nested arrays
```

## Output Formatting

### Indentation

```bash
jq --indent 2 '...' input.json > output.json
```

### YAML-safe filter storage

Store complex jq filters in YAML using block scalars to avoid escaping issues:

```yaml
filter: |-
  [.[] | select(.status == "active") | {...}]
  | sort_by(.field)
args:
  - "--indent 2"
```

**Critical rule**: Each `args` item must be a single string containing both the flag and its value — every item must start with `-`. Use `"--indent 2"` not `["--indent", "2"]`.

Use `|-` (strip trailing newline) rather than `|` to avoid a trailing `\n` in the filter string.

Reconstruct the command:

```bash
jq $(yq -r '.args[]' jq_args.yaml) "$(yq -r '.filter' jq_args.yaml)" input.json > output.json
```

## Verification Checklist

Before declaring a transformation complete:

- [ ] Record count matches expected (check at each filter stage)
- [ ] Sort order verified at boundaries (first/last entries, group transitions)
- [ ] Null/missing fields handled (test with records that have null values)
- [ ] String normalization applied consistently (whitespace, case)
- [ ] Output structure matches spec exactly (field names, nesting)
- [ ] `cmd.sh` reproduces identical output when re-run
- [ ] YAML round-trips correctly through `yq`

## Reference Implementation (v01)

The following working example demonstrates all four axes in combination. Input: an array of user records with `id`, `username`, `email`, `status`, `last_login`, `phone`, `roles` (array with whitespace/case variation), and `blocked_domains` (array). Output: filtered, normalized, reshaped, and sorted report.

### Full jq command

```bash
jq --indent 2 '[.[] |
  select(.status == "active") |
  (.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles |
  select($norm_roles | any(. == "admin" or . == "owner")) |
  (.email | split("@")[1] | ascii_downcase) as $email_domain |
  ((.blocked_domains // []) | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $blocked |
  select($blocked | any(. == $email_domain) | not) |
  {
    user_id: .id,
    username: .username,
    email: .email,
    email_domain: $email_domain,
    contact: "\(.username) <\(.email)>",
    phone: ((.phone // "") | gsub("^\\s+|\\s+$"; "") | if . == "" then "unknown" else . end),
    last_login: .last_login[0:10],
    account_summary: {
      role_count: ($norm_roles | length),
      primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
      roles: $norm_roles
    }
  }
] | sort_by(.email_domain) | group_by(.email_domain) | map(sort_by(.username) | reverse) | add // []' /app/users.json > /app/verified_admin_contacts.json
```

### YAML args file

```yaml
filter: |-
  [.[] |
    select(.status == "active") |
    (.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles |
    select($norm_roles | any(. == "admin" or . == "owner")) |
    (.email | split("@")[1] | ascii_downcase) as $email_domain |
    ((.blocked_domains // []) | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $blocked |
    select($blocked | any(. == $email_domain) | not) |
    {
      user_id: .id,
      username: .username,
      email: .email,
      email_domain: $email_domain,
      contact: "\(.username) <\(.email)>",
      phone: ((.phone // "") | gsub("^\\s+|\\s+$"; "") | if . == "" then "unknown" else . end),
      last_login: .last_login[0:10],
      account_summary: {
        role_count: ($norm_roles | length),
        primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
        roles: $norm_roles
      }
    }
  ] | sort_by(.email_domain) | group_by(.email_domain) | map(sort_by(.username) | reverse) | add // []
args:
  - "--indent 2"
```

### What this demonstrates per axis

- **Selection**: three chained `select()` calls (status, privileged role, not-blocked), with computed `$norm_roles` bound before the privilege check
- **Ordering**: group-then-reverse pattern for email_domain ASC + username DESC
- **Field derivation**: field renaming (`user_id`), computed field (`contact`), nested object (`account_summary`)
- **Value normalization**: regex trim + `ascii_downcase` for roles/blocked_domains/email_domain, null-safe phone with fallback, ISO date substring extraction
- **Aggregation**: `unique` for dedup+sort of roles, `length` for role_count, `.[0]` with null guard for primary_role

## References

- `references/jq_patterns.md` — Comprehensive jq idiom cheat sheet
- `references/yaml_filter_storage.md` — YAML storage patterns for jq filters
