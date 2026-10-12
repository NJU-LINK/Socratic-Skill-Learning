---
name: jq-data-processing
description: >
  Transform JSON data using jq pipelines with normalization, filtering,
  field derivation, aggregation, and multi-key sorting. Handles tasks
  requiring per-record value normalization (trim, lowercase, substring
  extraction, date parsing), selection predicates including cross-field
  exclusion rules, output record reshaping with nested objects, collection
  operations (deduplicate, count, group), and stable-sort-based mixed-direction
  ordering. Produces both the jq filter and a YAML args file for reproducible
  reconstruction.
---

# jq Data Processing

## Overview

This skill covers transforming JSON input into structured JSON output using `jq`.
The core workflow: analyze task requirements → build a jq filter through
normalization → selection → derivation → aggregation → ordering → package into
YAML args file and shell command.

## Procedure

### Step 1: Analyze the Task Requirements

Before writing any jq, decompose the task into these categories:

1. **Selection criteria**: What records pass through? (status filters, membership
   checks, exclusion rules). Note whether predicates operate on raw or normalized
   values.
2. **Output schema**: What fields appear in the output? Which are renamed, which
   are derived, which are combined from multiple sources?
3. **Value normalization**: What per-value transforms are needed? (trim whitespace,
   lowercase, extract substrings, parse dates, null/blank fallbacks)
4. **Aggregation**: What collection operations are needed? (deduplicate, count,
   sort arrays, group records, compute summaries)
5. **Sort order**: What keys and directions? (ascending, descending, multi-key)

### Step 2: Build the jq Filter

Structure the filter as a pipeline within `[.[] | ... ]` to process each record,
then apply final sorting to the collected array.

#### 2a. Normalization Phase — Compute Derived Values with `as $var` Bindings

Use `as $var` to compute normalized values before using them in predicates or
output. This avoids recomputation and keeps the logic clear.

**Common normalization patterns:**

```jq
# Trim whitespace + lowercase (the workhorse for string normalization)
gsub("^\\s+|\\s+$"; "") | ascii_downcase

# Extract domain from email
split("@") | .[1] | ascii_downcase

# ISO 8601 timestamp → YYYY-MM-DD date string
split("T")[0]

# Alternative: use capture for more complex date formats
capture("^(?<date>\\d{4}-\\d{2}-\\d{2})") | .date

# Null/blank fallback with default
if .field == null or (.field | gsub("^\\s+|\\s+$"; "") | length) == 0
then "default_value"
else (.field | gsub("^\\s+|\\s+$"; ""))
end
```

**Pattern**: Normalize an array field (e.g., roles) into a variable:
```jq
(.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $norm_roles
```

#### 2b. Selection Phase — Apply Predicates on Normalized Values

Apply filters AFTER normalization so predicates match correctly.

```jq
# Simple status filter
select(.status == "active")

# Membership check: does any normalized role match a target?
select($norm_roles | any(. == "admin" or . == "owner"))

# Cross-field exclusion: exclude records where a derived value appears in a list
# Pattern: normalize the list, then check if derived value is in it
(.blocked_domains | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $norm_blocked |
select([$norm_blocked[] | select(. == $email_domain)] | length == 0)

# Alternative exclusion using `any | not`:
select($email_domain as $d | $norm_blocked | any(. == $d) | not)
```

**Key insight**: Cross-field predicates (like blocked-domain exclusion) require
computing both sides in normalized form before comparing. Use `as $var` bindings
for both the derived value and the comparison list.

#### 2c. Derivation Phase — Build Output Records

Construct the output object using renamed fields, string interpolation for
combined fields, and inline nested objects.

```jq
{
  # Simple rename
  user_id: .id,

  # Keep as-is
  username: .username,

  # String interpolation combining fields
  contact: "\(.username) <\(.email)>",

  # Normalized derived value
  email_domain: $email_domain,

  # Conditional with fallback
  phone: (if .phone == null or (.phone | gsub("^\\s+|\\s+$"; "") | length) == 0
          then "unknown"
          else (.phone | gsub("^\\s+|\\s+$"; "")) end),

  # Nested output object
  account_summary: {
    role_count: ($sorted_roles | length),
    primary_role: (if ($sorted_roles | length) > 0 then $sorted_roles[0] else null end),
    roles: $sorted_roles
  }
}
```

#### 2d. Aggregation Phase — Collection Operations

```jq
# Deduplicate + sort in one step (unique returns sorted unique values)
$norm_roles | unique

# Count elements
$array | length

# First element or null (guard against empty array)
if ($array | length) > 0 then $array[0] else null end

# Grouping records (for cross-record aggregation)
group_by(.field) | map({key: .[0].field, count: length})
```

#### 2e. Ordering Phase — Multi-Key Mixed-Direction Sort

jq's `sort_by` is stable, enabling mixed-direction sorting by chaining:

```jq
# Sort by email_domain ascending, then username descending:
sort_by(.username) | reverse | sort_by(.email_domain)

# General pattern for primary ASC, secondary DESC:
sort_by(.secondary_key) | reverse | sort_by(.primary_key)
```

**Why this works**: jq's sort is stable, meaning equal elements retain their
relative order from the input. So:
1. `sort_by(.username) | reverse` → usernames descending
2. `sort_by(.email_domain)` → groups by domain ascending; within each group,
   the descending username order from step 1 is preserved.

**Limitation**: This stable-sort chaining trick only works cleanly for
primary-ASC + secondary-DESC. A naive `sort_by(.secondary) | sort_by(.primary) | reverse`
does NOT give primary-DESC + secondary-ASC — `reverse` flips the entire array,
reversing both keys. For primary-DESC + secondary-ASC, use `group_by(.primary_key) |`
`map(sort_by(.secondary_key)) | reverse` or negate numeric keys with `sort_by(-.key)`.

### Step 3: Package into YAML Args File

The YAML args file must survive a round-trip through `yq -r` without corruption.

**Critical: Use literal block scalar (`|-`) for the filter.**

```yaml
filter: |-
  [.[] |
    select(.status == "active") |
    (.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $norm_roles |
    ...
  ] | sort_by(.username) | reverse | sort_by(.email_domain)
args:
  - "--indent 2"
```

**Why `|-`?** YAML literal block scalars preserve content exactly as written.
No escape processing occurs. This means:
- `\\s+` in the YAML file → `\\s+` in the string value → jq sees `\s+` regex
  (whitespace class) ✓
- `"\(.field)"` string interpolation passes through unchanged ✓
- `$variable` references pass through unchanged ✓

**The backslash-doubling trap**: If you use YAML double-quoted strings instead,
you need quadruple backslashes (`\\\\s+`) because YAML processes `\\` → `\` and
then jq sees `\\s` as a literal backslash + `s`, not the whitespace class.
**Always use `|-` for jq filters in YAML.**

**Args format**: Each item in `args` is a complete argument (flag + value as one
string when applicable). The reconstruction command word-splits them:
```sh
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" input.json > output.json
```
- `$(yq -r '.args[]')` is unquoted → word-splits into separate arguments
- `"$(yq -r '.filter')"` is quoted → passes as single argument, preventing
  shell interpretation of `$`, `\`, and `"`

### Step 4: Write the Shell Command

Save the exact reconstruction command to `cmd.sh`:
```sh
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /app/output.json
```

### Step 5: Verify the Solution

Run these checks:

1. **Round-trip verification**: Run the reconstruction command and diff against
   a direct jq invocation to confirm YAML round-trip integrity.
2. **Record count**: Verify the expected number of records after filtering.
3. **Sort order**: Group by primary sort key, verify secondary sort direction
   within each group.
4. **Exclusion check**: Verify no records that should be excluded appear in output.
5. **Edge cases**: Check null/blank handling (phone fallback), empty arrays,
   records at boundaries.

```sh
# Round-trip check
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /tmp/reconstructed.json
diff /app/output.json /tmp/reconstructed.json

# Sort order check (example: primary=email_domain ASC, secondary=username DESC)
jq 'group_by(.email_domain) | map(
  {domain: .[0].email_domain,
   usernames: map(.username),
   correctly_sorted: (map(.username) == (map(.username) | sort | reverse))}
)' /app/output.json
```

## Key Patterns Reference

| Pattern | jq Expression |
|---------|--------------|
| Trim + lowercase | `gsub("^\\s+\\|\\s+$"; "") \| ascii_downcase` |
| Array normalize | `.arr \| map(trim_lower)` |
| Deduplicate + sort | `unique` |
| Any-match predicate | `any(. == "target")` |
| Exclusion predicate | `[list[] \| select(. == $val)] \| length == 0` |
| First-or-null | `if (arr \| length) > 0 then arr[0] else null end` |
| Null/blank fallback | `if . == null or (trim \| length) == 0 then default else trim end` |
| Date extract | `split("T")[0]` |
| Stable multi-sort | `sort_by(secondary) \| reverse \| sort_by(primary)` |
| String combine | `"\(.a) <\(.b)>"` |
| Nested output | `{outer: {inner: derived}}` |

## Variation Dimensions

This skill handles variation along four axes:

1. **Selection & Ordering Logic**: From simple status filters to multi-condition
   predicates, inclusion/exclusion across fields, multi-key sorting in mixed
   directions, and selection criteria that interact with derived values.

2. **Field Derivation & Reshaping**: From simple renames to deep field access,
   optional nested objects, combining multiple source fields, emitting nested
   output structures, and building records that differ substantially from input.

3. **Value Normalization**: From timestamp-to-date and null fallbacks to string
   cleanup, substring extraction, numeric coercion, boolean derivation, and
   complex per-value formatting rules.

4. **Aggregation & Collection Operations**: From per-record counting and
   first-element extraction to grouping, cross-record aggregation, deduplication,
   flattening/rebuilding arrays, and combining per-record transformation with
   collection-level summaries.
