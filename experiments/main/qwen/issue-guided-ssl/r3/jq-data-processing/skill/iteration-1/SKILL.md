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

## Adapting to New Tasks

When encountering a new task in this family:

1. **Identify the selection criteria**: What fields determine inclusion/exclusion? What predicates combine them?
2. **Identify normalization needs**: Which values need trimming, lowercasing, or other transformation before comparison?
3. **Identify field derivation**: What output fields are renamed, computed, combined, or nested?
4. **Identify aggregation**: Are there per-record aggregations (count, first, sum) or cross-record aggregations (group, deduplicate)?
5. **Identify sort specification**: What keys, what directions? Apply the stable-sort chaining pattern.
6. **Build incrementally**: Test each stage on a small sample before composing.

## Reference

See `references/jq-patterns.md` for a comprehensive catalog of reusable jq patterns organized by operation type.
