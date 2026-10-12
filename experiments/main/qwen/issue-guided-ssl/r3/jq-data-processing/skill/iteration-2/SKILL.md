---
name: jq-data-processing
description: >
  Reusable methodology for JSON-to-JSON data transformation pipelines using jq.
  Covers record selection/filtering, field derivation and reshaping, scalar value
  normalization, aggregation and collection operations, multi-key sorting with
  mixed directions, blocked-list exclusion via cross-field index checks, and
  artifact generation (output JSON, command script, YAML argument manifest).
---

# jq Data-Processing Skill

## Overview

This skill transforms JSON array inputs into reshaped JSON array outputs using `jq`. Every task in this family follows a **linear four-stage pipeline**:

```
input → [normalize intermediate values] → [filter/select records] → [reshape output fields] → [sort final array]
```

Build and test each stage independently before composing them.

## Pipeline Architecture

### Stage 1: Normalize Intermediate Values

Before any filtering or reshaping, compute normalized forms of values that will be compared or output. Define a reusable `normalize` function at the top of every filter:

```jq
def normalize: gsub("^\\s+|\\s+$"; "") | ascii_downcase;
```

This trims surrounding whitespace and lowercases. Apply it to:
- Role names (before checking privileged status, deduplication, and sorting)
- Blocked-domain entries (before comparing to email domain)
- Phone numbers (before output, with additional fallback logic)
- Any other string field requiring case/whitespace normalization

**Key insight**: Normalize *before* comparison, *before* deduplication, and *before* sorting. The order matters because `" Admin "` and `"admin"` must be treated as identical.

### Stage 2: Filter / Select Records

Common filter patterns:

**Status filter**: `select(.status == "active")` — or whatever status values the task requires.

**Cross-field exclusion (blocked-domain pattern)**:
```jq
(.email | split("@")[1] | ascii_downcase) as $email_domain |
(.blocked_domains // [] | map(normalize)) as $blocked |
select($blocked | index($email_domain) | not)
```
- Extract domain from email: split on `@`, take index `[1]`, lowercase.
- Normalize the entire blocked list.
- Use `index($val) | not` to check non-membership.
- Always use `// []` for null-safe fallback on array fields.

**Privileged role check** (after normalization):
```jq
(.roles // [] | map(normalize) | unique) as $norm_roles |
select($norm_roles | any(. == "admin" or . == "owner"))
```
- `unique` in jq both deduplicates AND sorts ascending — use the result directly for output.

**Multi-condition predicates**: Combine multiple `select()` calls (they act as AND). For OR logic, use `select(cond1 or cond2)`.

### Stage 3: Reshape Output Fields

Build the output object with derived fields:

**Field renaming**: `user_id: .id`
**String interpolation**: `contact: "\(.username) <\(.email)>"`
**ISO 8601 → YYYY-MM-DD**: `.last_login[0:10]` (first 10 chars) or `.last_login | split("T")[0]`
**Email domain extraction**: `.email | split("@")[1] | ascii_downcase`
**Phone fallback**:
```jq
(.phone // "" | gsub("^\\s+|\\s+$"; "")) as $trimmed |
(if $trimmed == "" then "unknown" else $trimmed end)
```
Handles both `null` and blank-after-trim cases.

**Nested output objects**:
```jq
account_summary: {
  role_count: ($norm_roles | length),
  primary_role: (if ($norm_roles | length) > 0 then $norm_roles[0] else null end),
  roles: $norm_roles
}
```

**Null propagation**: Use `// default_value` at every point where a source field might be null or missing.

### Stage 4: Sort Final Array

**Critical pattern for mixed-direction multi-key sorting**:

jq's `sort_by` always sorts ascending, and jq's sort is **stable** (equal elements preserve relative order). To sort by key A ascending, then key B descending:

```jq
| sort_by(.B) | reverse    # step 1: secondary key descending
| sort_by(.A)              # step 2: primary key ascending (stable preserves step 1 order)
```

**Always sort by the secondary key first, then the primary key.** This works because the stable sort in step 2 preserves the relative ordering from step 1 for records that share the same primary key value.

For more than two keys, extend the pattern: sort by the least-significant key first (with its direction), then progressively more significant keys.

## Value Normalization Patterns

| Operation | jq Pattern |
|-----------|-----------|
| Trim + lowercase | `gsub("^\\s+|\\s+$"; "") \| ascii_downcase` |
| Extract email domain | `split("@")[1] \| ascii_downcase` |
| ISO date → YYYY-MM-DD | `.[0:10]` or `split("T")[0]` |
| Null-safe fallback | `.field // "default"` |
| Blank → default | `gsub("^\\s+|\\s+$"; "") \| if . == "" then "default" else . end` |
| Numeric coercion | `tonumber` |
| Boolean derivation | `if .field == "yes" then true else false end` |
| String part extraction | `split("pattern") \| .[N]` |

## Aggregation and Collection Patterns

| Operation | jq Pattern |
|-----------|-----------|
| Deduplicate + sort | `unique` (deduplicates AND sorts ascending) |
| Count unique | `unique \| length` |
| Group by key | `group_by(.field)` |
| Flatten arrays | `[.[] \| .field] \| flatten` or `[.[] \| .field[]]` |
| Per-record aggregation | Compute within the record transformation using `as` bindings |
| Cross-record aggregation | Use `group_by` after initial transformation |

## Artifact Generation

Every task produces three artifacts:

1. **Output JSON** (`/app/<output_name>.json`): The transformed result, formatted with 2-space indentation (`--indent 2`).

2. **Command script** (`/app/cmd.sh`): The exact jq command including output redirection.

3. **YAML argument manifest** (`/app/jq_args.yaml`): Contains:
   - `filter`: the complete jq filter expression (use YAML block scalar `|` for multi-line)
   - `args`: list of strings, each being one jq argument (flag and value as separate items)

The reconstruction command:
```bash
jq $(yq -r '.args[]' /app/jq_args.yaml) "$(yq -r '.filter' /app/jq_args.yaml)" /app/<input>.json > /app/<output>.json
```

## Common Pitfalls

1. **`def` placement**: Definitions must come before the expression that uses them. Put all `def`s at the very top of the filter.

2. **`unique` vs `unique_by`**: `unique` deduplicates by value. `unique_by(f)` deduplicates by a key function. For normalized role strings, `unique` is correct.

3. **Null safety**: Always use `// []` or `// ""` or `// null` before operating on fields that might be missing. Missing fields cause jq errors, not null results.

4. **Sort direction**: `sort_by` is always ascending. For descending, use `sort_by(.key) | reverse`. For mixed directions, sort secondary key first.

5. **YAML escaping**: When embedding jq filters in YAML, use block scalars (`|`) to avoid escaping issues with backslashes and quotes.

6. **String interpolation in jq**: Use `"\(.field)"` syntax, not concatenation.

7. **Array wrapping**: When the filter produces individual objects via `.[] | ...`, wrap the entire expression in `[...]` to collect into an array before sorting.

## Pipeline Composition: Combining Per-Record and Cross-Record Operations

Many tasks require both per-record transformation AND cross-record aggregation in a single workflow. The key is to sequence these operations correctly:

### Pattern 1: Per-Record First, Then Cross-Record

Transform individual records, then aggregate across the transformed set:

```jq
[
  .[] |
  # Per-record transformation
  (.roles // [] | map(normalize) | unique) as $norm_roles |
  {
    user_id: .id,
    role_count: ($norm_roles | length),
    primary_role: $norm_roles[0]
  }
]
# Cross-record aggregation
| group_by(.primary_role)
| map({
    role: .[0].primary_role,
    user_count: length,
    users: [.[] | .user_id]
  })
```

### Pattern 2: Cross-Record First, Then Per-Record

Aggregate first, then transform each group:

```jq
group_by(.department) |
map({
  department: .[0].department,
  employees: [
    .[] |
    # Per-record transformation within each group
    {
      name: .name,
      salary: .salary,
      bonus: (.salary * 0.1)
    }
  ],
  total_salary: ([.[].salary] | add)
})
```

### Pattern 3: Intermediate Computation with Cross-Record Context

Compute a value that depends on the entire dataset, then use it per-record:

```jq
# Compute global average first
([.[].salary] | add / length) as $avg_salary |
[
  .[] |
  # Use the global value in per-record transformation
  {
    name: .name,
    salary: .salary,
    above_average: (.salary > $avg_salary)
  }
]
```

### Key Insight: Sequencing Matters

- **Per-record operations** (select, map, object construction) work on individual items
- **Cross-record operations** (group_by, unique on collected arrays, global aggregations) work on the entire dataset
- Use `as` bindings to capture intermediate values before crossing the boundary
- Wrap per-record results in `[...]` before applying cross-record operations

## Adapting to New Tasks: Decision Framework

When encountering a new task, work through these axes systematically:

### Axis 1: Selection and Ordering Logic

**Questions to ask:**
- What fields determine inclusion/exclusion?
- Are there multiple conditions (AND/OR)?
- Does selection depend on normalized values?
- Does selection depend on computed/derived values?

**Pattern selection:**
- Simple status filter → `select(.status == "value")`
- Multi-condition AND → chain multiple `select()` calls
- Multi-condition OR → `select(cond1 or cond2)`
- Exclusion based on cross-field comparison → normalize both sides, use `index() | not`
- Selection based on derived values → compute derived value with `as` binding, then `select()`

**Sorting:**
- Single key ascending → `sort_by(.key)`
- Single key descending → `sort_by(.key) | reverse`
- Multi-key, all same direction → `sort_by([.key1, .key2])`
- Multi-key, mixed directions → stable-sort chaining (sort secondary first, then primary)

### Axis 2: Field Derivation and Reshaping

**Questions to ask:**
- Which fields are renamed vs. kept as-is?
- Are there computed fields (combinations, transformations)?
- Is the output structure flat or nested?
- Do I need to extract parts of structured values?

**Pattern selection:**
- Simple rename → `new_name: .old_name`
- String combination → `"\(.field1) \(.field2)"`
- Extract from structured string → `split("delimiter")[index]`
- Nested output object → `nested: { inner: .value }`
- Array of objects → `[.[] | { ... }]`
- Flatten nested arrays → `[.[] | .array_field[]]`

### Axis 3: Value Normalization

**Questions to ask:**
- Which values need case normalization?
- Which values need whitespace trimming?
- Are there date/time conversions?
- Are there fallback defaults for missing/null values?
- Are there boolean derivations?

**Pattern selection:**
- Trim + lowercase → `def normalize: gsub("^\\s+|\\s+$"; "") | ascii_downcase;`
- Extract email domain → `split("@")[1] | ascii_downcase`
- ISO date → YYYY-MM-DD → `.[0:10]` or `split("T")[0]`
- Null fallback → `.field // "default"`
- Blank-after-trim fallback → `gsub("^\\s+|\\s+$"; "") | if . == "" then "default" else . end`
- Numeric coercion → `tonumber`
- Boolean derivation → `if .field == "yes" then true else false end`

**Critical rule**: Normalize BEFORE comparison, BEFORE deduplication, BEFORE sorting.

### Axis 4: Aggregation and Collection Operations

**Questions to ask:**
- Are there per-record aggregations (count, first, sum within each record)?
- Are there cross-record aggregations (group by, global summaries)?
- Do I need to deduplicate values?
- Do I need to flatten or rebuild arrays?

**Pattern selection:**
- Per-record count → `(.array_field | length)`
- Per-record first → `.array_field[0]`
- Per-record sum → `(.array_field | map(.value) | add)`
- Deduplicate + sort → `unique`
- Deduplicate by key → `unique_by(.field)`
- Group by key → `group_by(.field)`
- Flatten nested arrays → `[.[] | .array_field[]]` or `flatten`
- Cross-record summary → `group_by(.key) | map({key: .[0].key, count: length})`

**Composition**: See "Pipeline Composition" section above for combining per-record and cross-record operations.

### Build Strategy

1. **Start small**: Test each stage on 2-3 records before composing
2. **Use `as` bindings**: Capture intermediate normalized values to avoid recomputation
3. **Wrap in `[...]`**: Collect per-record results before cross-record operations
4. **Sort last**: Apply sorting after all transformations are complete
5. **Verify incrementally**: Check count, check a few records, check sorting

## Robustness Patterns

### Null Safety at Every Stage

```jq
# Array fields that might be missing
(.roles // [] | map(normalize))

# String fields that might be null
(.phone // "" | normalize)

# Numeric fields that might be missing
(.salary // 0)

# Nested objects that might be missing
(.address // {} | .city // "unknown")
```

### Empty Array Handling

```jq
# Check if array is empty before accessing
if (.roles | length) > 0 then .roles[0] else null end

# Provide default for empty arrays
(.roles // [] | if length == 0 then ["none"] else . end)
```

### Type Coercion Safety

```jq
# Ensure string before string operations
(.field // "" | tostring | normalize)

# Ensure number before numeric operations
(.field // 0 | tonumber)
```

## Reference

See `references/jq-patterns.md` for a comprehensive catalog of reusable jq patterns organized by operation type.
