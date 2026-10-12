---
name: jq-data-processing
description: >
  Transform JSON data using jq pipelines that combine record selection/filtering,
  field derivation/reshaping, value normalization, and aggregation/collection operations.
  Handles multi-condition predicates, mixed-direction sorting, nested output structures,
  string cleanup, null/blank fallbacks, deduplication, and per-record or cross-record
  summarization. Produces correctly formatted JSON output and saves reproducible
  command artifacts.
---

# jq Data Processing Skill

## Quick Start: Pipeline Template

For most tasks in this family, follow this structural pattern. Replace placeholders with task-specific values:

```jq
[.[] |
  # Step 1: Normalize collections (Axis 4)
  (ARRAY_FIELD // [] | map(NORMALIZE_FN) | unique) as $norm_list |
  # Note: `unique` both deduplicates AND sorts alphabetically
  
  # Step 2: Select/filter records (Axis 1)
  select(FILTER_PREDICATE) |
  
  # Step 3: Derive intermediate values
  (DERIVED_VALUE_EXPRESSION) as $var1 |
  (ANOTHER_DERIVED) as $var2 |
  
  # Step 4: Exclusion logic if needed (Axis 1)
  select(EXCLUSION_PREDICATE) |
  
  # Step 5: Reshape output (Axis 2)
  {
    OUTPUT_FIELD_1: SOURCE_EXPRESSION_1,
    OUTPUT_FIELD_2: SOURCE_EXPRESSION_2,
    NESTED_OBJECT: {
      nested_field: $var1,
      another_field: DERIVED_EXPRESSION
    }
  }
] | sort_by(SORT_EXPRESSION)
# For mixed-direction sort: sort_by([.asc_field, (.desc_field | explode | map(255 - .) | implode)])
```

**Placeholders to replace:**
- `ARRAY_FIELD`: The input array to normalize (e.g., `.roles`, `.tags`)
- `NORMALIZE_FN`: Normalization pipeline (e.g., `gsub("^\\s+|\\s+$"; "") | ascii_downcase`)
- `FILTER_PREDICATE`: Selection condition (e.g., `.status == "active" and ($norm_list | any)`)
- `DERIVED_VALUE_EXPRESSION`: Computed values (e.g., `.email | split("@")[1] | ascii_downcase`)
- `OUTPUT_FIELD_N`: Target field names in the output schema
- `SOURCE_EXPRESSION_N`: How to compute each output field
- `SORT_EXPRESSION`: Sort keys (e.g., `[.email_domain, .username]`)

**Key insight**: `unique` in jq both deduplicates AND sorts, so it does double-duty for array fields.

## Worked Example: Template Instantiation

Here's how the template above maps to a concrete task (selecting active accounts with privileged roles, excluding blocked domains):

```jq
[.[] |
  # ARRAY_FIELD = .roles, NORMALIZE_FN = trim+lowercase
  (.roles // [] | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase) | unique) as $norm_roles |
  
  # FILTER_PREDICATE = active + has admin or owner
  select(.status == "active" and ($norm_roles | map(. == "admin" or . == "owner") | any)) |
  
  # DERIVED_VALUE = email domain
  (.email | split("@")[1] | ascii_downcase) as $email_domain |
  
  # EXCLUSION = blocked domain check
  (.blocked_domains // [] | map(gsub("^\\s+|\\s+$"; "") | ascii_downcase)) as $bd |
  select($bd | index($email_domain) | not) |
  
  # OUTPUT RESHAPING
  {
    user_id: .id,
    username: .username,
    email_domain: $email_domain,
    phone: (if (.phone // "" | gsub("^\\s+|\\s+$"; "")) == "" then "unknown" else (.phone | gsub("^\\s+|\\s+$"; "")) end),
    last_login: (.last_login | .[0:10]),
    account_summary: {
      role_count: ($norm_roles | length),
      primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
      roles: $norm_roles
    }
  }
] | sort_by([.email_domain, (.username | explode | map(255 - .) | implode)])
```

## When to Deviate from the Template

The basic template handles per-record filtering and reshaping. Deviate when:

**Cross-record aggregation** (e.g., group summaries, department-level stats):
- Collect first with `[.[] | ...]`, then apply `group_by(.field)` on the result
- Example: `[.[] | select(...) | {...}] | group_by(.department) | map({dept: .[0].department, count: length})`

**Multi-step pipelines** (filter → group → aggregate → reshape):
- Use intermediate `as $` bindings to hold computed values across pipeline stages
- Example: `[.[] | ...] as $filtered | $filtered | group_by(...) | ...`

**Both per-record and cross-record output in same array**:
- May need to compute cross-record stats first, then join back to per-record output
- Example: Compute totals with `reduce` or `group_by`, store in `$totals`, then reference in per-record reshape

**Complex exclusion logic** (e.g., exclude based on computed values):
- Compute the value first with `as $var`, then use it in the exclusion predicate
- The template's Step 4 shows this pattern with blocked domains

## Overview

This skill covers JSON-to-JSON transformation tasks using `jq`. Tasks in this family
require building a single jq pipeline (or program) that:

1. **Selects** records based on one or more conditions
2. **Reshapes** fields into a new output structure
3. **Normalizes** scalar values (trimming, case-folding, defaults, date extraction)
4. **Aggregates** per-record collections (dedup, sort, count, pick-first)
5. **Sorts** the final array, possibly with mixed ascending/descending keys
6. **Saves** the command and filter in specified artifact formats

## General Workflow

```
1. Inspect input JSON structure (fields, types, nesting)
2. Identify selection criteria (status, role membership, exclusion lists)
3. Identify normalization rules (trim, lowercase, defaults, date parsing)
4. Identify output schema (renamed fields, computed fields, nested objects)
5. Identify aggregation needs (unique, sort, count, first/last)
6. Identify sort order (single key, multi-key, mixed directions)
7. Adapt the template above, testing incrementally
8. Write output artifacts (filter file, YAML args, shell command)
9. Verify round-trip: reconstruct command from artifacts and diff output
```

## Reference: Axis 1 — Selection and Ordering Logic

### Filtering with `select()`

Single condition:
```jq
.[] | select(.status == "active")
```

Multi-condition (AND):
```jq
.[] | select(.status == "active" and .type == "premium")
```

Multi-condition (OR):
```jq
.[] | select(.role == "admin" or .role == "owner")
```

Existence check within an array field:
```jq
.[] | select((.roles // []) | map(. == "admin" or . == "owner") | any)
```

Exclusion based on a list (e.g., blocked domains):
```jq
.email_domain as $ed |
(.blocked_domains // [] | map(normalize)) as $bd |
select($bd | index($ed) | not)
```

### Sorting

Single key ascending:
```jq
sort_by(.username)
```

Multi-key ascending:
```jq
sort_by([.email_domain, .username])
```

**Descending string sort within `sort_by`** — jq's `sort_by` only sorts ascending.
To invert a string key, transform each character's codepoint:
```jq
sort_by([.email_domain, (.username | explode | map(255 - .) | implode)])
```
This maps each character to `chr(255 - codepoint)`, so ascending sort on the
transformed string produces descending order on the original.

For descending numeric sort, negate: `sort_by(-.count)`.

## Reference: Axis 2 — Field Derivation and Reshaping

### Object Construction

Rename fields:
```jq
{ user_id: .id, name: .username }
```

Computed/derived fields using string interpolation:
```jq
{ contact: "\(.username) <\(.email)>" }
```

Nested output objects:
```jq
{
  user_id: .id,
  account_summary: {
    role_count: (.roles | length),
    primary_role: (.roles | sort | .[0]),
    roles: (.roles | sort)
  }
}
```

### Accessing Nested Data

Extract from array context:
```jq
.email | split("@")[1]   # domain from email
```

Safe access with defaults:
```jq
(.metadata.tags // []) | map(...)
```

### Collecting into Array

Wrap the entire pipeline in `[...]` to collect results:
```jq
[.[] | select(...) | { ... }]
```

## Reference: Axis 3 — Value Normalization

### Trimming Whitespace

jq 1.6 has no `trim` builtin. Use `gsub`:
```jq
gsub("^\\s+|\\s+$"; "")
```

### Case Normalization

```jq
ascii_downcase
```

### Combined Trim + Lowercase

```jq
gsub("^\\s+|\\s+$"; "") | ascii_downcase
```

### Null/Blank Fallback

When a field may be `null`, empty string, or whitespace-only:
```jq
(.phone // "" | gsub("^\\s+|\\s+$"; "")) as $trimmed |
if $trimmed == "" then "unknown" else $trimmed end
```

Or inline:
```jq
phone: (if (.phone // "" | gsub("^\\s+|\\s+$"; "")) == ""
        then "unknown"
        else (.phone | gsub("^\\s+|\\s+$"; ""))
        end)
```

### Date Extraction from ISO 8601

ISO 8601 timestamps like `"2026-03-16T05:01:40.829540Z"` — the first 10 characters
are always `YYYY-MM-DD`:
```jq
.last_login | .[0:10]
```

### Domain Extraction from Email

```jq
.email | split("@")[1] | ascii_downcase
```

### Numeric Coercion

```jq
.value | tonumber
(.percentage / 100)
```

### Boolean Derivation

```jq
(.roles | length > 0)
(.status == "active")
```

## Reference: Axis 4 — Aggregation and Collection Operations

### Deduplication

```jq
.roles | map(normalize) | unique
```

**Critical**: `unique` both deduplicates AND sorts alphabetically. This is the key insight that makes `unique` do double-duty (dedup + sort the role list in one call).

If you need dedup without sort, use `group_by(.) | map(.[0])`.

### Sorting Arrays

```jq
.roles | sort          # ascending alphabetical
.roles | sort_by(-.)   # descending (numeric)
```

### Counting

```jq
.roles | length
```

### First/Last Element

```jq
.roles | sort | .[0]    # first (smallest)
.roles | sort | .[-1]   # last (largest)
```

### Null-safe first element

```jq
if (.roles | length) > 0 then .roles | sort | .[0] else null end
```

### Grouping Records

```jq
group_by(.department) | map({
  dept: .[0].department,
  count: length,
  members: [.[].username]
})
```

### Flattening Arrays

```jq
[.[].tags] | add        # flatten array of arrays
[.[].tags[]]            # alternative: iterate and collect
```

### Cross-record Aggregation

```jq
group_by(.category) |
map({
  category: .[0].category,
  total: (map(.amount) | add),
  avg: ((map(.amount) | add) / length)
})
```

## Artifact Management

### Filter File Approach

Write the jq filter to a file to avoid shell quoting issues:
```bash
cat > /app/filter.jq << 'JQEOF'
[.[] |
  ...filter body...
] | sort_by(...)
JQEOF

jq --indent 2 -f /app/filter.jq /app/input.json > /app/output.json
```

The quoted heredoc delimiter `'JQEOF'` prevents shell interpretation of `$`,
backticks, and backslashes — content is written literally.

### YAML Argument File

When the task requires saving jq arguments to YAML for reconstruction:

```yaml
filter: |
  [.[] |
    ...filter body...
  ] | sort_by(...)
args:
  - "--indent 2"
```

**Critical**: Use YAML literal block scalar (`|`) for the filter. This preserves
newlines and backslashes exactly as written.

### Round-trip Verification

Always verify the YAML round-trip before considering the task done:

```bash
# 1. Extract and test the filter
jq "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /tmp/test.json

# 2. Compare against direct execution
jq -f /app/filter.jq /app/input.json > /tmp/direct.json
diff /tmp/test.json /tmp/direct.json

# 3. Run the full reconstruction command
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /app/output.json
```

### Shell Command File

Save the exact reconstruction command:
```bash
cat > /app/cmd.sh << 'CMDEOF'
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/input.json > /app/output.json
CMDEOF
chmod +x /app/cmd.sh
```

## Common Pitfalls

1. **Backslash escaping in YAML**: `\\s+` in jq must remain `\\s+` in the YAML
   file. Using `|` block scalar with quoted heredoc prevents double-escaping.

2. **Null handling**: `.phone | gsub(...)` fails if `.phone` is null. Always use
   `(.phone // "") | gsub(...)` or check for null first.

3. **Case sensitivity in comparisons**: Email domains, role names, and blocked
   lists often have mixed case. Normalize both sides before comparing.

4. **`unique` vs `sort`**: `unique` deduplicates AND sorts. If the task says
   "deduplicate then sort", `unique` alone suffices. If it says "sort then
   deduplicate keeping first occurrence", use `sort | group_by(.) | map(.[0])`.

5. **`sort_by` with mixed directions**: Cannot use `reverse` on a multi-key sort.
   Use the codepoint-inversion trick for descending string keys.

6. **Array wrapping**: Forgetting `[...]` around the pipeline produces individual
   JSON objects instead of a JSON array. The output format usually requires an array.

7. **`--indent 2`**: Many tasks require pretty-printed JSON with 2-space indent.
   Pass `--indent 2` to jq.

## Testing Strategy

Build the filter incrementally:
1. Start with selection only — verify count and which records pass
2. Add normalization — verify normalized values on a few sample records
3. Add output reshaping — verify field names and computed values
4. Add aggregation — verify role counts, sorted arrays, first elements
5. Add sorting — verify first and last records in output
6. Test edge cases: null phones, blank phones, mixed-case domains, duplicate roles
7. Verify artifact round-trip produces identical output
