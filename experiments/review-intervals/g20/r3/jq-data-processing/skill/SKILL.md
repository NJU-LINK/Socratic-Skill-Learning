---
name: jq-data-processing
description: Transform JSON data using jq with filtering, normalization, aggregation, and reshaping operations
---

# jq Data Processing Skill

This skill covers transforming JSON arrays of records using jq, including filtering, field extraction, value normalization, aggregation, and output formatting.

## Task Analysis Framework

Before writing jq code, systematically analyze the task along these four dimensions:

### 1. Selection and Ordering Logic
**Questions to answer:**
- What filtering conditions apply? (status, field values, array membership)
- Are there multiple conditions? (AND/OR logic)
- What sorting is required? (single key, multiple keys, ascending/descending)
- Do sort criteria interact with derived values?

**jq patterns:**
```jq
# Single condition
select(.status == "active")

# Multiple conditions
select(.status == "active" and .type == "admin")

# Array contains value
select([.roles[] | select(. == "admin")] | length > 0)

# Negation / exclusion
select(.blocked_domains | any(. == $domain) | not)

# Multi-key sort (all ascending)
sort_by(.field1, .field2)

# Mixed sort directions (ascending by field1, descending by field2)
sort_by(.field1, .field2) | group_by(.field1) | map(reverse) | add // []
```

### 2. Field Derivation and Reshaping
**Questions to answer:**
- Which input fields map to output fields? (direct copy, rename, transform)
- Are there computed/derived fields? (concatenation, extraction, calculation)
- What is the output structure? (flat object, nested objects, arrays)
- Do fields need to be combined or split?
- Are fields optional or potentially missing/null?

**jq patterns:**
```jq
# Rename field
{new_name: .old_field}

# Extract from nested structure
{domain: (.email | split("@") | .[1])}

# Combine multiple fields
{contact: "\(.username) <\(.email)>"}

# Build nested object
{
  account_summary: {
    role_count: (.roles | length),
    roles: .roles
  }
}

# Conditional field inclusion
(if .phone then {phone: .phone} else {} end)

# Safe navigation for optional nested objects
# Use // to provide defaults for missing/null fields
{city: (.address.city // "unknown")}

# Check if field exists before accessing
(if .profile? then .profile.name else "N/A" end)

# Handle potentially missing array fields
{tags: (.tags // [])}
```

### 3. Value Normalization
**Questions to answer:**
- What string transformations are needed? (trim, lowercase, extract parts)
- Are there type conversions? (string to number, timestamp to date)
- What are the fallback/default values for missing data?
- When should normalization happen? (before comparison, before deduplication, before output)

**Critical principle:** Normalize values BEFORE using them in comparisons, deduplication, or sorting.

**jq patterns:**
```jq
# Trim whitespace and lowercase
gsub("^\\s+|\\s+$"; "") | ascii_downcase

# Extract domain from email
split("@") | .[1] | ascii_downcase

# Handle null/blank with fallback
if .phone == null or (.phone | gsub("^\\s+|\\s+$"; "") | length == 0) 
then "unknown" 
else (.phone | gsub("^\\s+|\\s+$"; "")) 
end

# Extract date from ISO timestamp
split("T") | .[0]

# Structured string extraction with regex
# Use capture() for named groups
"2026-03-16T05:01:40Z" | capture("(?<year>\\d{4})-(?<month>\\d{2})-(?<day>\\d{2})")
# → {"year": "2026", "month": "03", "day": "16"}

# Use scan() for multiple matches
"v1.2.3-beta" | scan("\\d+")  # → ["1", "2", "3"]

# Use match() for first match with position
"Error 404: Not Found" | match("Error (\\d+)")
# → {"offset": 0, "length": 9, "string": "Error 404", "captures": [...]}

# Numeric coercion
tonumber

# Boolean derivation
(if .status == "active" then true else false end)
```

### 4. Aggregation and Collection Operations
**Questions to answer:**
- Are there per-record aggregations? (count items in array, sum values)
- Are there cross-record aggregations? (group by field, compute totals)
- Do arrays need deduplication, flattening, or rebuilding?
- What collection-level summaries are needed?
- **Does the task combine per-record transformation with cross-record aggregation?**

**jq patterns:**
```jq
# Deduplicate and sort array
.roles | unique

# Count unique items after normalization
.roles | map(ascii_downcase) | unique | length

# Get first item or null
.roles | .[0]  # Returns null if empty

# Group records by field
group_by(.department)

# Aggregate over groups
group_by(.department) | map({
  dept: .[0].department,
  count: length,
  names: [.[].username]
})

# Flatten nested arrays
[.[].tags[]] | unique

# Compute summary statistics
{
  total: length,
  avg_age: (map(.age) | add / length)
}
```

#### Per-record → Cross-record Bridge

**Critical architectural pattern:** When a task requires both per-record transformation AND cross-record aggregation, use the two-phase architecture:

```jq
[.[] | per-record-transform] | cross-record-operations
```

**How it works:**
1. `.[]` decomposes the input array into individual records
2. The per-record pipeline transforms each record (normalize, filter, derive fields)
3. `[...]` collects the transformed records back into an array
4. After the closing `]`, you operate on the entire collected array

**Variable scoping:** Variables created with `as $var` inside the brackets are scoped to each record. Outside the brackets, you're working with the full result set.

**Example: Top users per department by role count**
```jq
[
  .[] |
  # Per-record: normalize, filter, derive
  (.roles | map(gsub("^\\s+"; "") | ascii_downcase) | unique) as $norm_roles |
  select(.status == "active") |
  {name: .username, role_count: ($norm_roles | length), dept: .department}
]
# Cross-record: the array above is now a single value you can aggregate
| group_by(.dept)
| map({
    department: .[0].dept,
    total_users: length,
    top_user: (sort_by(-.role_count) | .[0].name)
  })
```

**Key insight:** Everything after the closing `]` operates on the entire collected array, not on individual records. This pattern is essential when selection criteria interact with derived values computed during the per-record phase.

## Core Workflow

1. **Analyze the task** using the framework above - identify which variations are present
2. **Sample the input data** - examine 2-3 records to understand structure (don't read entire file)
3. **Build the jq filter incrementally** - test each stage before combining
4. **Save artifacts correctly**:
   - `cmd.sh`: Complete jq command with input/output files
   - `jq_args.yaml`: Filter expression and any jq arguments (excluding input/output files)
5. **Test the reconstruction command** - verify that `jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /app/output.json` produces identical output

## YAML Escaping Rules

**Critical**: When storing jq code in YAML files, count the escaping layers:

- **YAML block scalar (`|`)**: Completely literal - write code exactly as jq should receive it
  - `"` → write as `"` (not `\"`)
  - jq's `\s` (regex escape) → write as `\s` (not `\\s`)
- **YAML quoted strings**: Require escaping
  - `"` → write as `\"`
  - `\s` → write as `\\s`

**Always test the reconstruction command** to catch escaping errors.

## Verification Checklist

- [ ] Filter produces correct record count
- [ ] Exclusions work correctly (check specific known cases)
- [ ] Sorting order is correct (verify first/last items per group)
- [ ] Field transformations produce expected values
- [ ] Null/blank handling works correctly
- [ ] YAML escaping is correct (test reconstruction command)
- [ ] Empty result case handled (use `// []` after `add`)
- [ ] Output JSON is properly formatted (2-space indentation by default)

## Defensive Programming and Edge Cases

When building robust jq transformations, anticipate and handle edge cases:

### Missing or Null Fields
```jq
# Provide default for missing/null field
.phone // "unknown"

# Safe navigation with optional operator (?)
.profile?.name  # Returns null if .profile is missing

# Check existence before access
(if .address? then .address.city else "N/A" end)

# Handle missing arrays
.roles // [] | length
```

### Empty Arrays
```jq
# Check if array is empty before accessing
(if (.roles | length) > 0 then .roles[0] else null end)

# Provide default for empty results
[.[] | select(.active)] | if length == 0 then [] else . end

# Use // [] after operations that might return null
[.[] | .tags[]] // []
```

### Type Safety
```jq
# Ensure field is string before string operations
(if (.phone | type) == "string" then (.phone | gsub("\\s"; "")) else "unknown" end)

# Coerce types explicitly
.age | tostring
.count | tonumber

# Handle mixed types in arrays
[.items[] | if type == "string" then . else tostring end]
```

### Malformed Data
```jq
# Validate email format before extracting domain
(if (.email | test("@")) then (.email | split("@") | .[1]) else "invalid" end)

# Validate date format before parsing
(if (.timestamp | test("^\\d{4}-\\d{2}-\\d{2}")) then (.timestamp | split("T") | .[0]) else "unknown" end)

# Filter out invalid records
[.[] | select(.id != null and .username != null)]
```

### Testing Edge Cases
Always test your filter with:
- Empty input array: `[] | your_filter`
- Records with missing fields
- Records with null values
- Records with empty arrays
- Records with unexpected types

## Debugging Tips

1. **Sample first, don't read everything** - use `jq '.[0:3]'` to examine structure
2. **Test filtering separately** - extract just the IDs of matching records
3. **Verify exclusions** - check specific records that should be excluded
4. **Check sorting** - show first/last items per group to verify order
5. **Test reconstruction** - always run the exact command the evaluator will use
6. **Compare outputs** - use `diff` to verify cmd.sh and reconstruction produce identical results

## Example: Multi-Stage Pipeline (Two-Phase Architecture)

This example demonstrates the **per-record → cross-record bridge** pattern. The `[.[] | ...]` wrapper transforms each record individually, then the operations after `]` aggregate across the entire result set.

```jq
[
  .[] |
  # === PHASE 1: Per-record transformation ===
  # Variables scoped to each record:
  (.roles | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles |
  
  # Filter by status (per-record)
  select(.status == "active") |
  
  # Filter by array content (per-record)
  select([$norm_roles[] | select(. == "admin" or . == "owner")] | length > 0) |
  
  # Compute derived values (per-record)
  (.email | split("@") | .[1] | ascii_downcase) as $email_domain |
  (.blocked_domains | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $norm_blocked |
  
  # Exclude based on computed values (per-record)
  select($norm_blocked | any(. == $email_domain) | not) |
  
  # Build output object (per-record)
  {
    user_id: .id,
    username: .username,
    email_domain: $email_domain,
    contact: "\(.username) <\(.email)>",
    account_summary: {
      role_count: ($norm_roles | length),
      primary_role: $norm_roles[0],
      roles: $norm_roles
    }
  }
]
# === PHASE 2: Cross-record aggregation ===
# Everything after ] operates on the entire collected array:
| sort_by(.email_domain, .username)
| group_by(.email_domain)
| map(reverse)
| add // []
```

## Key Principles

1. **Analyze before coding** - use the task analysis framework to decompose requirements
2. **Normalize before comparing** - trim whitespace and lowercase before any equality checks
3. **Normalize before deduplicating** - ensure unique() works on normalized values
4. **Use variables for computed values** - `as $var` makes code clearer and allows reuse
5. **Two-phase architecture** - `[.[] | per-record-transform] | cross-record-operations` bridges per-record and cross-record work
6. **Defensive programming** - anticipate missing/null fields, empty arrays, type mismatches; use `//` for defaults and `?` for safe navigation
7. **Test edge cases** - null values, empty arrays, blank strings, mixed case, missing fields
8. **Verify the full pipeline** - don't assume intermediate stages work; test the complete transformation
9. **Always test reconstruction** - the YAML escaping is a common source of errors
