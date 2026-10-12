---
name: jq-data-processing
description: >
  Transform JSON arrays into reshaped, filtered, normalized, and sorted reports
  using jq. Covers multi-condition selection, field derivation and restructuring,
  scalar normalization (trimming, case folding, date extraction, fallback
  defaults), per-record aggregation, and multi-key mixed-direction sorting.
---

# jq Data Processing

## Overview

This skill covers building jq pipelines that read a JSON array of records and
produce a transformed JSON array as output. The transformation typically
involves four concerns that can be addressed independently and composed:

1. **Selection** — filtering records by status, role membership, exclusion
   lists, or other predicates.
2. **Reshaping** — building output objects with renamed fields, derived values,
   nested structures, or combined fields.
3. **Normalization** — cleaning scalar values (trimming whitespace, lowercasing,
   extracting date parts, applying fallback defaults for null/blank).
4. **Aggregation** — deduplicating arrays, counting items, picking first/last,
   grouping, or computing per-record summaries from collections.

## Methodology: Build Incrementally

Always develop the filter in stages, testing each stage before composing:

### Stage 1 — Normalize early, store as fields

Compute all normalized values at the start of the pipeline and attach them as
temporary fields on each record. This avoids repeating normalization in filters
and output construction.

```jq
.[] |
  .email_domain = (.email | split("@") | last | ascii_downcase) |
  .norm_roles = ([.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] | unique) |
  .norm_blocked = [.blocked_domains[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase]
```

Key normalization patterns:
- **Trim + lowercase**: `gsub("^\\s+|\\s+$"; "") | ascii_downcase`
- **Extract email domain**: `split("@") | last | ascii_downcase`
- **Deduplicate + sort**: `unique` (already returns sorted in jq)
- **Date extraction**: `split("T") | .[0]` for ISO 8601 → YYYY-MM-DD

### Stage 2 — Apply selection filters

Chain `select()` calls for each condition. Common patterns:

```jq
# Status filter
select(.status == "active")

# Membership test (at least one role matches)
select([.norm_roles[] | select(. == "admin" or . == "owner")] | length > 0)

# Exclusion test (email domain NOT in blocked list)
select(.email_domain as $ed | .norm_blocked | index($ed) == null)

# Multi-field inclusion/exclusion
select(.type == "premium" and .region != "restricted")
```

### Stage 3 — Build output objects

Construct the final record shape, using normalized fields computed in Stage 1:

```jq
{
  user_id: .id,
  username,
  email,
  email_domain,
  contact: "\(.username) <\(.email)>",
  phone: (if .phone == null or (.phone | gsub("^\\s+|\\s+$"; "")) == ""
          then "unknown"
          else (.phone | gsub("^\\s+|\\s+$"; "")) end),
  last_login: (.last_login | split("T") | .[0]),
  account_summary: {
    role_count: (.norm_roles | length),
    primary_role: (if (.norm_roles | length) > 0 then .norm_roles[0] else null end),
    roles: .norm_roles
  }
}
```

Value normalization patterns:
- **Null-or-blank fallback**: `(.field | gsub("^\\s+|\\s+$"; "")) as $t | if .field == null or $t == "" then "default" else $t end`
- **String interpolation**: `"\(.field1) <\(.field2)>"`
- **Nested output objects**: just nest `{}` inside the outer object
- **Optional field access**: `.field // "default"` or explicit null checks

### Stage 4 — Sort with mixed directions

jq's `sort_by` is **stable** and always ascending. For multi-key sorts with
mixed directions, use a two-pass stable sort technique:

```jq
# Sort by email_domain ASC, then username DESC:
sort_by(.username) | reverse | sort_by(.email_domain)
```

**Why this works**: Pass 1 sorts by the secondary key (username) and reverses
for descending. Pass 2 sorts by the primary key (email_domain) ascending;
because `sort_by` is stable, ties in email_domain preserve the existing
username-descending order.

**Do NOT** attempt `sort_by([.email_domain, -.username])` — negating strings
does not work in jq.

General pattern for N-key mixed-direction sort:
1. Sort by the lowest-priority key first (and reverse if descending)
2. Then sort by the next-higher-priority key (and reverse if descending)
3. Continue until the highest-priority key is sorted last

## Artifact Files

### jq_args.yaml

Always use a YAML **literal block scalar** (`|`) for the filter to avoid
escaping issues with backslashes, quotes, and parentheses in jq expressions.

**Critical constraint**: Every item in the `args` list **must start with `-`**.
The test validates `arg.startswith("-")` for each item. This means:
- Flag+value must be combined as one item: `"--indent=2"` (not two items)
- Or use `args: []` if no flags are needed

**Recommended approach**: Use `args: []` when possible. jq 1.6's default
pretty-print output already uses 2-space indentation, so `--indent 2` is
usually unnecessary. This avoids the flag+value formatting issue entirely.

```yaml
filter: |
  [.[] | .email_domain = ... | select(...) | {...}] | sort_by(...) | ...
args: []
```

If you must pass flags, combine flag+value with `=`:

```yaml
filter: |
  [.[] | ...]
args:
  - "--indent=2"
```

The reconstruction command is:

```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /app/output.json
```

When `args: []`, the `$(yq -r '.args[]' ...)` expands to nothing, so the
command becomes: `jq "<filter>" /app/input.json > /app/output.json`

### cmd.sh

Save the exact reconstruction command as shown above.

## Common jq Patterns Reference

| Need | Pattern |
|------|---------|
| Trim whitespace | `gsub("^\\s+\\|\\s+$"; "")` |
| Lowercase | `ascii_downcase` |
| Deduplicate + sort | `unique` |
| Check membership | `[.arr[] \| select(. == "val")] \| length > 0` |
| Check non-membership | `.arr \| index($val) == null` |
| Null-safe fallback | `.field // "default"` |
| Null-or-blank fallback | `(.f \| gsub("^\\s+\|\\s+$"; "")) as $t \| if .f == null or $t == "" then "x" else $t end` |
| ISO date → YYYY-MM-DD | `.ts \| split("T") \| .[0]` |
| String interpolation | `"\(.a) <\(.b)>"` |
| Stable descending sort | `sort_by(.key) \| reverse` |
| Multi-key mixed sort | `sort_by(.secondary) \| reverse \| sort_by(.primary)` |
| Count array | `.arr \| length` |
| First element or null | `if (.arr \| length) > 0 then .arr[0] else null end` |
| Group by key | `group_by(.key) \| map({key: .[0].key, count: length})` |
| Frequency map | `reduce .[] as $x ({}; .[$x.key] += 1)` |
| Flatten nested array | `[.[] \| .items[]]` |
| Safe numeric coercion | `.val \| tonumber? // 0` |
| Regex capture | `.str \| capture("^(?<p>\\d+)") \| .p` |

## Adaptation Guide

When facing a new variant of this task family:

1. **Read the task carefully** to identify: what fields to filter on, what
   output shape is required, what normalizations are needed, what sort order.
2. **Map each requirement** to one of the four concerns (selection, reshaping,
   normalization, aggregation).
3. **Build the pipeline** following the four-stage methodology above.
4. **Test each stage** independently before composing.
5. **Verify edge cases**: null values, whitespace-only strings, case
   variations, empty arrays, records that should be excluded.

## Complete Working Example

Here's a complete working example for a typical task:

**Task**: Filter active users with admin/owner roles, exclude blocked domains, normalize fields, sort by domain ASC then username DESC.

**jq_args.yaml**:
```yaml
filter: |
  [.[] | 
    .email_domain = (.email | split("@") | last | ascii_downcase) |
    .norm_roles = ([.roles[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] | unique) |
    .norm_blocked = [.blocked_domains[] | gsub("^\\s+|\\s+$"; "") | ascii_downcase] |
    select(.status == "active") |
    select([.norm_roles[] | select(. == "admin" or . == "owner")] | length > 0) |
    select(.email_domain as $ed | .norm_blocked | index($ed) == null) |
    {
      user_id: .id,
      username,
      email,
      email_domain,
      contact: "\(.username) <\(.email)>",
      phone: (if .phone == null or (.phone | gsub("^\\s+|\\s+$"; "")) == "" 
              then "unknown" 
              else (.phone | gsub("^\\s+|\\s+$"; "")) end),
      last_login: (.last_login | split("T") | .[0]),
      account_summary: {
        role_count: (.norm_roles | length),
        primary_role: (if (.norm_roles | length) > 0 then .norm_roles[0] else null end),
        roles: .norm_roles
      }
    }
  ] | sort_by(.username) | reverse | sort_by(.email_domain)
args: []
```

**cmd.sh**:
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/users.json > /app/output.json
```

## Common Pitfalls

1. **args format constraint**: Every item in `args` list must start with `-`. 
   - ❌ Wrong: `args: ["--indent", "2"]` (second item doesn't start with `-`)
   - ✅ Right: `args: []` (preferred, jq 1.6 defaults to 2-space indent)
   - ✅ Right: `args: ["--indent=2"]` (combined flag=value)

2. **Regex escaping in YAML**: Use literal block scalar (`|`) for filter to avoid 
   escaping backslashes. Inside the jq filter, use `\\s` for whitespace matching.

3. **Stable sort for mixed directions**: Don't try `sort_by([.a, -.b])` — negating 
   strings doesn't work. Use the two-pass technique instead.

4. **Normalization order**: Normalize values BEFORE filtering and deduplication. 
   Store normalized values as temporary fields to avoid repeating the transformation.

## Advanced Patterns

### Aggregation: Grouping and Summarizing

When tasks require cross-record aggregation (grouping, counting, summing), use `group_by`:

```jq
# Group by category, compute per-group summaries
[.[] | .category = (.type | ascii_downcase)] |
group_by(.category) |
map({
  category: .[0].category,
  count: length,
  avg_value: (map(.value) | add / length),
  items: [.[] | {id, name}]
})
```

For frequency maps or accumulators, use `reduce`:

```jq
# Count occurrences of each role across all users
reduce .[].roles[] as $role ({}; .[$role] += 1)

# Build a map of user_id -> role_count
reduce .[] as $u ({}; .[$u.id] = ($u.roles | length))
```

Combine per-record transformation with aggregation:

```jq
# Transform records, then group and summarize
[.[] | {user_id: .id, domain: (.email | split("@") | last)}] |
group_by(.domain) |
map({
  domain: .[0].domain,
  user_count: length,
  user_ids: [.[].user_id]
})
```

### Reshaping: Flattening and Expanding

Flatten nested arrays:

```jq
# Expand one-to-many: each user-tag pair becomes a record
[.[] | .tags[] | {user_id: .id, tag: .}]

# Flatten nested arrays while preserving parent context
[.[] | .items[] | {parent: .parent_id, item: .}]
```

Access optional nested objects with fallbacks:

```jq
{
  contact: (.metadata.contact // "N/A"),
  phone: (.metadata.phone // .fallback_phone // "unknown")
}
```

### Value Normalization: Coercion and Extraction

Numeric coercion with error handling:

```jq
# Convert string to number, default to 0 if invalid
.value = (.value | tonumber? // 0)

# Clamp numeric values
.score = ([.score | tonumber, 0] | max) | ([., 100] | min)
```

Boolean derivation:

```jq
.is_active = (.status == "active")
.has_permission = ([.permissions[] | select(. == "admin")] | length > 0)
```

Extract parts of structured strings:

```jq
# Extract date from ISO timestamp using capture
.date = (.timestamp | capture("^(?<date>[^T]+)T") | .date)

# Extract domain from email using split
.domain = (.email | split("@") | last)

# Extract numeric prefix from mixed strings
.code = (.mixed | capture("^(?<num>\\d+)") | .num | tonumber)
```
